"""RQ jobs that process an uploaded session: proxy transcode, detection and tracking, teams, then metrics."""

import asyncio
import io
import json
import re
import uuid
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pyarrow as pa
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis import metrics as m
from app.analysis.detector import BALL, PERSON, Detector, get_detector
from app.analysis.pitch import fit_homography, project
from app.analysis.summary import build_summary
from app.analysis.teams import assign_teams, torso_feature
from app.analysis.tracking import analyse_video
from app.analysis.tracks_io import read_tracks, write_tracks
from app.config import get_settings
from app.models import Calibration, Session, SessionTrack, SessionVideo
from app.sessions.service import STOPPED_UNEXPECTEDLY, list_videos, session_prefix
from app.storage.base import Storage, get_storage
from app.storage.local import scratch_dir
from app.video.ffmpeg import transcode_proxy
from app.worker.runtime import run_async

CLS_NAMES = {PERSON: "person", BALL: "ball"}
PROGRESS_STEP = 2  # progress is committed only when it moves at least this far
TRANSCODE_SHARE, ANALYSE_SHARE = 0.20, 0.75  # of a video's slice of the first 95 %; teams take the last 5 %
TRUNCATED_BELOW = 0.9  # analysed frames / expected frames
MIN_PLAYERS_FOR_QUALITY = 6
ERROR_MAX_CHARS = 500
_PATH_RE = re.compile(r"(?<![\w.])(?:/[^\s'\"]+)+")


def _public_error(exc: Exception) -> str:
    """A short message for the UI: no traceback text and no file paths."""
    text = _PATH_RE.sub("<path>", str(exc).split("Traceback")[0]).strip()
    return (text or type(exc).__name__)[:ERROR_MAX_CHARS]


def _keys(prefix: str) -> tuple[str, str]:
    return f"{prefix}/analysis/tracks.parquet", f"{prefix}/analysis/summary.json"


def _json_bytes(doc: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(doc).encode())


async def process_session_core(db: AsyncSession, storage: Storage, detector: Detector, session_id: uuid.UUID, *,
                               sample_fps: float, tile_far_half: bool) -> None:
    s = await db.get(Session, session_id)
    assert s is not None
    try:
        await _process(db, storage, detector, s, sample_fps, tile_far_half)
    except BaseException as exc:  # also CancelledError / SystemExit: the row must never stay 'processing'
        error = _public_error(exc) if isinstance(exc, Exception) else STOPPED_UNEXPECTEDLY
        await db.rollback()
        await db.execute(update(Session).where(Session.id == session_id).values(status="failed", error=error))
        await db.commit()
        raise


async def _process(db: AsyncSession, storage: Storage, detector: Detector, s: Session, sample_fps: float,
                   tile_far_half: bool) -> None:
    loop = asyncio.get_running_loop()
    prefix = session_prefix(s)
    s.status, s.progress, s.stage, s.error = "processing", 0, None, None
    await db.commit()
    videos = await list_videos(db, s.id)
    total_ms = sum(v.duration_ms or 0 for v in videos) or 1
    last_written = 0

    async def report(value: float) -> None:
        nonlocal last_written
        pct = min(99, int(value))
        if pct >= last_written + PROGRESS_STEP:
            last_written = s.progress = pct
            await db.commit()

    async def set_stage(stage: str) -> None:
        s.stage = stage
        await db.commit()

    def threadsafe(base: float, weight: float, offset: float, scale: float) -> Callable[[float], None]:
        """A worker-thread progress callback mapping a stage fraction onto the session's overall percentage."""
        def on_progress(fraction: float) -> None:
            value = 100 * (base + weight * (offset + scale * fraction))
            asyncio.run_coroutine_threadsafe(report(value), loop).result()
        return on_progress

    tables: list[pa.Table] = []
    torso: dict[int, list[np.ndarray]] = {}
    quality_videos: list[dict] = []
    t_offset_ms, next_track_id, done = 0, 1, 0.0
    for video in videos:
        weight = (video.duration_ms or 0) / total_ms if any(v.duration_ms for v in videos) else 1 / len(videos)
        src = storage.local_path(video.original_key)
        if src is None:
            raise RuntimeError("the original video is not available on local storage")
        proxy_key = f"{prefix}/proxy/{video.id}.mp4"
        await set_stage("transcoding")
        with scratch_dir() as tmp:
            dest = Path(tmp) / "proxy.mp4"
            await asyncio.to_thread(transcode_proxy, src, dest,
                                    threadsafe(done, weight, 0.0, TRANSCODE_SHARE))
            storage.import_file(proxy_key, dest)
        video.proxy_key = proxy_key
        await db.commit()

        await set_stage("analysing")
        # Analysis reads the original: calibration points are picked on its frames, and the proxy is for playback.
        result = await asyncio.to_thread(
            analyse_video, src, str(video.id), detector, sample_fps, t_offset_ms, next_track_id,
            tile_far_half, threadsafe(done, weight, TRANSCODE_SHARE, ANALYSE_SHARE))
        tables.append(result.table)
        for tid, crops in result.torso_samples.items():
            torso.setdefault(tid, []).extend(crops)
        if len(result.table):
            next_track_id = max(next_track_id, int(result.table["track_id"].to_numpy().max()) + 1)
        expected = round((video.duration_ms or 0) / 1000 * sample_fps)
        quality_videos.append({"video_id": str(video.id), "frames": result.frames, "expected_frames": expected,
                               "truncated": expected > 0 and result.frames < TRUNCATED_BELOW * expected})
        t_offset_ms += video.duration_ms or 0
        done += weight * (TRANSCODE_SHARE + ANALYSE_SHARE)

    await set_stage("teams")
    table = pa.concat_tables(tables)
    track_ids = table["track_id"].to_numpy()
    classes = table["cls"].to_numpy()
    t_ms = table["t_ms"].to_numpy()
    order = np.argsort(track_ids, kind="stable")
    uniq, starts = np.unique(track_ids[order], return_index=True)
    groups = np.split(order, starts[1:])
    frames_count = {int(tid): len(g) for tid, g in zip(uniq, groups)}
    person_ids = [int(tid) for tid, g in zip(uniq, groups) if classes[g[0]] == PERSON]
    teams = assign_teams({tid: torso_feature(torso.get(tid, [])) for tid in person_ids}, frames_count)

    tracks_key, _ = _keys(prefix)
    with scratch_dir() as tmp:
        write_tracks(table, Path(tmp) / "tracks.parquet")
        storage.import_file(tracks_key, Path(tmp) / "tracks.parquet")

    await db.execute(delete(SessionTrack).where(SessionTrack.session_id == s.id))
    db.add_all(SessionTrack(
        customer_id=s.customer_id, session_id=s.id, track_id=int(tid), cls=CLS_NAMES[int(classes[g[0]])],
        team=teams.get(int(tid)) if classes[g[0]] == PERSON else None, frames_count=len(g),
        first_ms=int(t_ms[g].min()), last_ms=int(t_ms[g].max())) for tid, g in zip(uniq, groups))
    for video in videos:
        video.status = "processed"
    s.quality = {"videos": quality_videos}
    await db.commit()

    await compute_metrics_core(db, storage, s.id)  # an uncalibrated session gets a summary without metrics
    s.status, s.progress, s.stage = "ready", 100, None
    await db.commit()


async def compute_metrics_core(db: AsyncSession, storage: Storage, session_id: uuid.UUID) -> None:
    """Fill person metrics from the stored tracks and write summary.json; never touches status.

    The session and calibration are read fresh: a calibration or sprint threshold saved while the session was
    processing must count. Without a tracks file (nothing processed yet, or processing failed) it does nothing.
    """
    s = await db.get(Session, session_id, populate_existing=True)
    assert s is not None
    tracks_key, summary_key = _keys(session_prefix(s))
    tracks_path = storage.local_path(tracks_key)
    if tracks_path is None:
        raise RuntimeError("the tracks file is not available on local storage")
    if not tracks_path.is_file():
        return
    videos = await list_videos(db, session_id)
    cal = await db.get(Calibration, s.calibration_id, populate_existing=True) if s.calibration_id else None
    table = read_tracks(tracks_path)
    sample_fps = get_settings().analysis_sample_fps
    duration_ms = sum(v.duration_ms or 0 for v in videos)

    rows = {r.track_id: r for r in (await db.execute(
        select(SessionTrack).where(SessionTrack.session_id == session_id))).scalars()}
    is_person = table["cls"].to_numpy() == PERSON
    person = table.filter(pa.array(is_person))
    p_tid, p_t = person["track_id"].to_numpy(), person["t_ms"].to_numpy()

    prior_videos = (s.quality or {}).get("videos", [])
    total_frames = sum(v["frames"] for v in prior_videos) or len(np.unique(p_t))
    _, per_frame = np.unique(p_t, return_counts=True)
    persons_per_frame = per_frame.tolist() + [0] * max(0, total_frames - len(per_frame))
    lengths_s = [(r.last_ms - r.first_ms) / 1000 for r in rows.values() if r.cls == "person"]
    qual = {**m.quality(persons_per_frame, lengths_s, cal is not None, MIN_PLAYERS_FOR_QUALITY)}
    if prior_videos:
        qual["videos"] = prior_videos

    overview: dict[str, dict] = {}
    intensity: list[dict] = []
    shape: list[dict] = []
    if cal is not None:
        pitch = (float(cal.pitch_length_m), float(cal.pitch_width_m))
        H = fit_homography([tuple(p) for p in cal.image_points], [tuple(p) for p in cal.pitch_points])
        xy_all = project(H, m.foot_points(person))
        sprint = float(s.sprint_threshold_kmh)
        order = np.argsort(p_tid, kind="stable")
        uniq, starts = np.unique(p_tid[order], return_index=True)
        tracks: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        results: dict[int, dict] = {}
        for tid, g in zip(uniq, np.split(order, starts[1:])):
            tracks[int(tid)] = (p_t[g], xy_all[g])
        for tid, (t, xy) in tracks.items():
            row = rows.get(tid)
            if row is None:
                continue
            row.metrics = results[tid] = m.track_metrics(t, xy, sprint, pitch)
            row.on_pitch = m.is_on_pitch(xy, pitch)
        team_of = {tid: r.team for tid, r in rows.items() if r.team in ("a", "b")}
        intensity = m.intensity_timeline(tracks=tracks, teams=team_of, pitch=pitch)
        shape = m.team_shape(tracks=tracks, teams=team_of, pitch=pitch)
        for team in ("a", "b"):
            mine = [results[tid] for tid in results if team_of.get(tid) == team and rows[tid].on_pitch]
            samples = sum(r["samples"] for r in mine)
            heat = np.zeros(m.HEATMAP_SHAPE)
            for r in mine:
                heat += np.array(r["heatmap"]) * r["samples"]
            overview[team] = {
                "players_on_pitch_avg": samples / total_frames if total_frames else 0.0,
                "distance_m_total": sum(r["distance_m"] for r in mine),
                "heatmap": (heat / samples if samples else heat).tolist(),
            }

    summary = build_summary(duration_ms=duration_ms, sample_fps=sample_fps, calibrated=cal is not None,
                            quality=qual, teams_overview=overview, intensity=intensity, team_shape=shape,
                            tracks_total=len(rows))
    storage.save(summary_key, _json_bytes(summary))
    s.quality, s.summary_key = qual, summary_key
    await db.flush()


def process_session(session_id: str) -> None:
    settings = get_settings()
    storage, detector = get_storage(), get_detector()
    run_async(lambda db: process_session_core(
        db, storage, detector, uuid.UUID(session_id), sample_fps=settings.analysis_sample_fps,
        tile_far_half=settings.analysis_tile_far_half))


def compute_session_metrics(session_id: str) -> None:
    storage = get_storage()
    run_async(lambda db: compute_metrics_core(db, storage, uuid.UUID(session_id)))

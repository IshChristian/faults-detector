import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.analysis.tracks_io import read_tracks
from app.models import Session, SessionTrack, SessionVideo
from app.sessions.service import session_prefix
from app.video.ffmpeg import probe
from app.worker.session_jobs import compute_metrics_core, process_session_core
from tests.fakes import ScriptedDetector, two_players_and_ball
from tests.media import make_clip
from tests.test_calibration_api import _calibrate
from tests.test_sessions_api import _create, _site_with_camera

FPS = 10.0


class RaisingDetector:
    def detect(self, frame):
        raise RuntimeError("model exploded reading /srv/media/secret/clip.mp4\nTraceback (most recent call last):\n  File x")


async def _setup(client, db_session, tenant, media_storage, tmp_path, n_videos=2, declared_ms=None):
    customer, _, headers = await tenant("operator")
    site, cam = await _site_with_camera(db_session, customer)
    sid = uuid.UUID((await _create(client, headers, site, cam))["id"])
    s = await db_session.get(Session, sid)
    for i in range(n_videos):
        clip = make_clip(tmp_path / f"c{i}.mp4", seconds=2, size="320x180", fps=25,
                         creation_time=f"2026-11-01T09:0{i}:00Z")
        info = probe(clip)
        vid = uuid.uuid4()
        key = f"{session_prefix(s)}/original/{vid}.mp4"
        media_storage.import_file(key, clip)
        db_session.add(SessionVideo(
            id=vid, customer_id=customer.id, session_id=sid, position=i, size_bytes=1, original_key=key,
            duration_ms=declared_ms or info.duration_ms, fps=info.fps, width=info.width, height=info.height,
            creation_time=datetime(2026, 11, 1, 9, i, tzinfo=timezone.utc), status="uploaded"))
    await db_session.flush()
    return s, headers


async def _run(db_session, media_storage, s, detector=None):
    await process_session_core(db_session, media_storage, detector or ScriptedDetector(two_players_and_ball), s.id,
                               sample_fps=FPS, tile_far_half=False)
    await db_session.refresh(s)


async def _videos(db_session, sid):
    return list((await db_session.execute(
        select(SessionVideo).where(SessionVideo.session_id == sid).order_by(SessionVideo.position))).scalars())


async def test_process_produces_proxies_parquet_tracks_and_ready_status(client, db_session, tenant, media_storage, tmp_path):
    s, _ = await _setup(client, db_session, tenant, media_storage, tmp_path)
    await _run(db_session, media_storage, s)
    assert s.status == "ready" and s.progress == 100 and s.stage is None and s.error is None
    videos = await _videos(db_session, s.id)
    prefix = session_prefix(s)
    for v in videos:
        await db_session.refresh(v)
        assert v.status == "processed" and v.proxy_key == f"{prefix}/proxy/{v.id}.mp4"
        assert media_storage.exists(v.proxy_key)
    table = read_tracks(media_storage.local_path(f"{prefix}/analysis/tracks.parquet"))
    by_video = {}
    for row in table.to_pylist():
        by_video.setdefault(row["video_id"], []).append(row["t_ms"])
    assert set(by_video) == {str(v.id) for v in videos}
    assert min(by_video[str(videos[0].id)]) < 2000 and min(by_video[str(videos[1].id)]) >= 2000
    rows = list((await db_session.execute(select(SessionTrack).where(SessionTrack.session_id == s.id))).scalars())
    assert {r.cls for r in rows} == {"person", "ball"} and len(rows) == 6  # 2 players + ball in each video
    assert all(r.metrics is None and r.on_pitch is None for r in rows)
    assert all(r.team is None for r in rows if r.cls == "ball")
    assert all(r.team in ("a", "b", "other") for r in rows if r.cls == "person")


async def test_progress_is_monotonic_and_reaches_100(client, db_session, tenant, media_storage, tmp_path, monkeypatch):
    s, _ = await _setup(client, db_session, tenant, media_storage, tmp_path)
    seen = []
    real_commit = db_session.commit

    async def spy():
        await real_commit()
        seen.append(await db_session.scalar(select(Session.progress).where(Session.id == s.id)))

    monkeypatch.setattr(db_session, "commit", spy)
    await _run(db_session, media_storage, s)
    assert seen == sorted(seen) and seen[-1] == 100
    assert len({p for p in seen if 0 < p < 100}) >= 3  # intermediate steps were reported
    steps = [b - a for a, b in zip(seen, seen[1:]) if b < 100 and a > 0 and b != a]
    assert all(d >= 2 for d in steps)


async def test_uncalibrated_session_gets_summary_without_metrics(client, db_session, tenant, media_storage, tmp_path):
    s, _ = await _setup(client, db_session, tenant, media_storage, tmp_path)
    await _run(db_session, media_storage, s)
    assert s.calibration_id is None and s.quality["calibrated"] is False
    summary = json.loads(media_storage.open(s.summary_key).read())
    assert summary["calibrated"] is False and summary["tracks_total"] == 6
    persons = (await db_session.execute(select(SessionTrack).where(
        SessionTrack.session_id == s.id, SessionTrack.cls == "person"))).scalars()
    assert all(p.metrics is None for p in persons)


async def test_calibration_then_metrics_fills_track_metrics_and_summary(client, db_session, tenant, media_storage, tmp_path):
    s, headers = await _setup(client, db_session, tenant, media_storage, tmp_path)
    await _run(db_session, media_storage, s)
    r = await _calibrate(client, headers, str(s.id))
    assert r.status_code == 201, r.text
    await db_session.refresh(s)
    await compute_metrics_core(db_session, media_storage, s.id)
    await db_session.refresh(s)
    assert s.status == "ready" and s.quality["calibrated"] is True
    summary = json.loads(media_storage.open(s.summary_key).read())
    assert summary["calibrated"] is True
    rows = list((await db_session.execute(select(SessionTrack).where(SessionTrack.session_id == s.id))).scalars())
    for row in rows:
        await db_session.refresh(row)
        if row.cls == "person":
            assert "distance_m" in row.metrics and row.on_pitch is not None
        else:
            assert row.metrics is None and row.on_pitch is None


async def test_failure_marks_session_failed_with_short_error(client, db_session, tenant, media_storage, tmp_path):
    s, _ = await _setup(client, db_session, tenant, media_storage, tmp_path)
    with pytest.raises(RuntimeError):
        await _run(db_session, media_storage, s, RaisingDetector())
    await db_session.refresh(s)
    assert s.status == "failed" and s.stage == "analysing"
    assert s.error and len(s.error) <= 500
    assert "Traceback" not in s.error and "/srv" not in s.error and "secret" not in s.error


async def test_reprocess_replaces_tracks_not_duplicates(client, db_session, tenant, media_storage, tmp_path):
    s, _ = await _setup(client, db_session, tenant, media_storage, tmp_path)
    await _run(db_session, media_storage, s)
    await _run(db_session, media_storage, s)
    count = await db_session.scalar(select(func.count()).select_from(SessionTrack).where(SessionTrack.session_id == s.id))
    assert count == 6 and s.status == "ready"


async def test_truncated_video_is_flagged_in_quality_without_failing(client, db_session, tenant, media_storage, tmp_path):
    # The first video is declared 10 s long but only holds 2 s of frames, as ffmpeg gives for a truncated mp4.
    s, _ = await _setup(client, db_session, tenant, media_storage, tmp_path, n_videos=1, declared_ms=10_000)
    await _run(db_session, media_storage, s)
    assert s.status == "ready"
    (v,) = await _videos(db_session, s.id)
    (entry,) = s.quality["videos"]
    assert entry["video_id"] == str(v.id) and entry["truncated"] is True
    assert entry["frames"] == 20 and entry["expected_frames"] == 100


async def test_complete_video_is_not_flagged_truncated(client, db_session, tenant, media_storage, tmp_path):
    s, _ = await _setup(client, db_session, tenant, media_storage, tmp_path)
    await _run(db_session, media_storage, s)
    assert [v["truncated"] for v in s.quality["videos"]] == [False, False]


async def test_summary_endpoint_409_until_ready_then_signed_proxy_urls(client, db_session, tenant, media_storage, tmp_path):
    s, headers = await _setup(client, db_session, tenant, media_storage, tmp_path)
    r = await client.get(f"/api/v1/sessions/{s.id}/summary", headers=headers)
    assert r.status_code == 409 and r.json()["type"].endswith("not-ready")
    await _run(db_session, media_storage, s)
    r = await client.get(f"/api/v1/sessions/{s.id}/summary", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["calibrated"] is False
    videos = await _videos(db_session, s.id)
    assert [p["video_id"] for p in body["proxies"]] == [str(v.id) for v in videos]
    assert body["proxies"][0]["t_offset_ms"] == 0 and body["proxies"][1]["t_offset_ms"] == videos[0].duration_ms
    assert all("sig=" in p["url"] and f"/proxy/{p['video_id']}.mp4" in p["url"] for p in body["proxies"])

    tracks = await client.get(f"/api/v1/sessions/{s.id}/tracks?cls=person", headers=headers)
    assert tracks.status_code == 200
    items = tracks.json()
    assert len(items) == 4 and {t["cls"] for t in items} == {"person"}
    assert set(items[0]) == {"track_id", "cls", "team", "team_corrected", "on_pitch", "frames_count", "first_ms",
                             "last_ms", "metrics"}

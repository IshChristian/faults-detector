"""Sample frames, detect players and the ball, and track them with ByteTrack into a tracks table."""

import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pyarrow as pa
import supervision as sv

from app.analysis.detector import BALL, PERSON, Detections, Detector, detect_with_far_half_tiling
from app.analysis.tracks_io import TRACKS_SCHEMA
from app.video.ffmpeg import iter_frames, probe

TORSO_SAMPLES_PER_TRACK = 20
TORSO_SIZE = 16
# Torso region of a person box: 20-55 % of its height, 25-75 % of its width.
_TORSO_Y = (0.20, 0.55)
_TORSO_X = (0.25, 0.75)


@dataclass
class VideoAnalysis:
    table: pa.Table
    torso_samples: dict[int, list[np.ndarray]]  # track_id -> up to 20 RGB torso crops, 16x16
    frames: int
    persons_per_frame: list[int]


def _torso_crop(frame_bgr: np.ndarray, box_rel: np.ndarray) -> np.ndarray | None:
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = box_rel
    bw, bh = x2 - x1, y2 - y1
    cx1, cx2 = int(round((x1 + _TORSO_X[0] * bw) * w)), int(round((x1 + _TORSO_X[1] * bw) * w))
    cy1, cy2 = int(round((y1 + _TORSO_Y[0] * bh) * h)), int(round((y1 + _TORSO_Y[1] * bh) * h))
    cx1, cx2 = max(0, cx1), min(w, max(cx2, cx1 + 1))
    cy1, cy2 = max(0, cy1), min(h, max(cy2, cy1 + 1))
    crop = frame_bgr[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None
    small = cv2.resize(crop, (TORSO_SIZE, TORSO_SIZE), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2RGB)  # frames are BGR; stored crops are RGB


def _track(tracker: sv.ByteTrack, det: Detections, mask: np.ndarray, w: int, h: int) -> sv.Detections:
    scale = np.array([w, h, w, h], np.float32)
    sv_det = sv.Detections(
        xyxy=(det.xyxy[mask] * scale).astype(np.float32).reshape(-1, 4),
        confidence=det.score[mask].astype(np.float32),
        class_id=det.cls[mask].astype(int),
    )
    return tracker.update_with_detections(sv_det)


def analyse_video(
    path: Path,
    video_id: str,
    detector: Detector,
    sample_fps: float,
    t_offset_ms: int,
    first_track_id: int,
    tile_far_half: bool = False,
    on_progress: Callable[[float], None] | None = None,
) -> VideoAnalysis:
    info = probe(path)
    expected = max(1, round(info.duration_ms / 1000 * sample_fps))
    # Separate trackers so a ball can never steal (or be matched to) a person's identity.
    trackers = {PERSON: sv.ByteTrack(frame_rate=round(sample_fps)), BALL: sv.ByteTrack(frame_rate=round(sample_fps))}
    session_ids: dict[tuple[int, int], int] = {}  # (cls, raw tracker id) -> session-unique id
    cols: dict[str, list] = {name: [] for name in TRACKS_SCHEMA.names}
    torso: dict[int, list[np.ndarray]] = {}
    seen: dict[int, int] = {}
    rngs: dict[int, random.Random] = {}
    persons_per_frame: list[int] = []
    frames = 0

    for t_ms, frame in iter_frames(path, sample_fps):
        h, w = frame.shape[:2]
        det = detect_with_far_half_tiling(detector, frame) if tile_far_half else detector.detect(frame)
        persons = 0
        for cls, tracker in trackers.items():
            tracked = _track(tracker, det, det.cls == cls, w, h)
            for k in range(len(tracked)):
                raw = int(tracked.tracker_id[k])
                if raw < 0:
                    continue
                key = (cls, raw)
                if key not in session_ids:
                    session_ids[key] = first_track_id + len(session_ids)
                tid = session_ids[key]
                box = (tracked.xyxy[k] / np.array([w, h, w, h], np.float32)).astype(np.float32)
                cols["video_id"].append(video_id)
                cols["t_ms"].append(t_offset_ms + t_ms)
                cols["track_id"].append(tid)
                cols["cls"].append(cls)
                for name, v in zip(("x1", "y1", "x2", "y2"), box):
                    cols[name].append(float(v))
                cols["score"].append(float(tracked.confidence[k]))
                if cls == PERSON:
                    persons += 1
                    crop = _torso_crop(frame, box)
                    if crop is not None:
                        _reservoir_add(torso, seen, rngs, tid, crop)
        persons_per_frame.append(persons)
        frames += 1
        if on_progress:
            on_progress(min(1.0, frames / expected))

    if on_progress:
        on_progress(1.0)
    table = pa.Table.from_pydict(cols, schema=TRACKS_SCHEMA)
    return VideoAnalysis(table, torso, frames, persons_per_frame)


def _reservoir_add(
    store: dict[int, list[np.ndarray]], seen: dict[int, int], rngs: dict[int, random.Random], tid: int, crop: np.ndarray
) -> None:
    """Algorithm R, seeded per track id, so every crop of a track has equal odds of being kept."""
    n = seen[tid] = seen.get(tid, 0) + 1
    bucket = store.setdefault(tid, [])
    if len(bucket) < TORSO_SAMPLES_PER_TRACK:
        bucket.append(crop)
        return
    j = rngs.setdefault(tid, random.Random(tid)).randrange(n)
    if j < TORSO_SAMPLES_PER_TRACK:
        bucket[j] = crop

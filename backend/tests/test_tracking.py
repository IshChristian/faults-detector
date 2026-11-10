import numpy as np
import pytest

from app.analysis.detector import BALL, PERSON, Detections
from app.analysis.tracking import analyse_video
from app.analysis.tracks_io import TRACKS_SCHEMA, read_tracks, write_tracks
from app.video.ffmpeg import iter_frames
from tests.fakes import ScriptedDetector, make_detections, two_players_and_ball
from tests.media import make_clip


@pytest.fixture
def clip(tmp_path):
    return make_clip(tmp_path / "c.mp4", seconds=3, size="320x180", fps=25)


def _run(clip, detector=None, **kw):
    kw.setdefault("t_offset_ms", 0)
    kw.setdefault("first_track_id", 1)
    return analyse_video(clip, "v1", detector or ScriptedDetector(two_players_and_ball), 10, **kw)


def _rows(result, cls):
    return [r for r in result.table.to_pylist() if r["cls"] == cls]


def test_two_moving_players_keep_stable_ids(clip):
    res = _run(clip)
    assert res.frames == 30
    assert res.persons_per_frame == [2] * 30
    rows = _rows(res, PERSON)
    ids = {r["track_id"] for r in rows}
    assert len(ids) == 2
    for tid in ids:
        mine = sorted((r for r in rows if r["track_id"] == tid), key=lambda r: r["t_ms"])
        assert len(mine) == 30
        xs = [r["x1"] for r in mine]
        assert all(b > a for a, b in zip(xs, xs[1:]))


def test_track_ids_are_offset_for_session_uniqueness(clip):
    res = _run(clip, first_track_id=100)
    ids = set(res.table["track_id"].to_pylist())
    assert ids == {100, 101, 102}  # two players and the ball, consecutive


def test_t_ms_includes_video_offset(clip):
    res = _run(clip, t_offset_ms=60000)
    t = res.table["t_ms"].to_pylist()
    assert min(t) == 60000 and max(t) == 60000 + 2900


def test_ball_is_tracked_separately_from_people(clip):
    res = _run(clip)
    ball = _rows(res, BALL)
    person_ids = {r["track_id"] for r in _rows(res, PERSON)}
    assert len(ball) == 30
    assert len({r["track_id"] for r in ball}) == 1
    assert not ({r["track_id"] for r in ball} & person_ids)


def test_torso_samples_capped_at_20(clip):
    res = _run(clip)
    person_ids = {r["track_id"] for r in _rows(res, PERSON)}
    assert set(res.torso_samples) == person_ids  # no ball crops
    for crops in res.torso_samples.values():
        assert len(crops) == 20  # 30 frames seen, reservoir keeps 20
        assert all(c.shape == (16, 16, 3) and c.dtype == np.uint8 for c in crops)


def test_torso_crops_are_rgb(clip):
    # The testsrc2 frame is not uniform, so instead script a box and check channel order on a known colour.
    res = _run(clip, ScriptedDetector([make_detections([(0.0, 0.0, 1.0, 1.0)], [PERSON])] * 3))
    crop = next(iter(res.torso_samples.values()))[0]
    frame = next(iter_frames(clip, 10))[1]
    h, w = frame.shape[:2]
    ref = frame[int(0.2 * h) : int(0.55 * h), int(0.25 * w) : int(0.75 * w)]
    ref_mean_rgb = ref[..., ::-1].reshape(-1, 3).mean(axis=0)
    assert np.abs(crop.reshape(-1, 3).mean(axis=0) - ref_mean_rgb).max() < 12


def test_progress_reaches_one(clip):
    seen: list[float] = []
    _run(clip, on_progress=seen.append)
    assert seen and seen[-1] == 1.0 and seen == sorted(seen)
    assert all(0.0 <= p <= 1.0 for p in seen)


def test_frames_without_detections_are_counted(clip):
    res = _run(clip, ScriptedDetector([Detections.empty()] * 30))
    assert res.frames == 30 and res.table.num_rows == 0 and res.persons_per_frame == [0] * 30
    assert res.table.schema == TRACKS_SCHEMA


def test_parquet_roundtrip_keeps_schema(clip, tmp_path):
    res = _run(clip)
    assert res.table.schema == TRACKS_SCHEMA
    dest = tmp_path / "tracks.parquet"
    write_tracks(res.table, dest)
    back = read_tracks(dest)
    assert back.schema == TRACKS_SCHEMA
    assert back.equals(res.table)

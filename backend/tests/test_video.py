from datetime import UTC, datetime

import pytest

from app.video.ffmpeg import (
    VideoError,
    extract_frame,
    iter_frames,
    probe,
    transcode_proxy,
)
from tests.media import make_clip


def test_probe_reads_basic_info(tmp_path):
    info = probe(make_clip(tmp_path / "a.mp4", seconds=3, size="640x360", fps=25))
    assert (info.width, info.height) == (640, 360)
    assert abs(info.fps - 25) < 0.01
    assert 2900 <= info.duration_ms <= 3100
    assert info.creation_time == datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    assert info.codec == "h264"


def test_probe_without_creation_time_is_none(tmp_path):
    info = probe(make_clip(tmp_path / "a.mp4", seconds=1, creation_time=None))
    assert info.creation_time is None


def test_probe_rejects_non_video(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_text("definitely not a video")
    with pytest.raises(VideoError, match="not a readable video"):
        probe(bad)


def test_probe_and_frames_respect_display_rotation(tmp_path):
    clip = make_clip(tmp_path / "r.mp4", seconds=1, size="640x360", rotation=90)
    info = probe(clip)
    assert (info.width, info.height) == (360, 640)
    _, frame = next(iter_frames(clip, 10))
    assert frame.shape[:2] == (640, 360)


def test_iter_frames_samples_at_requested_fps(tmp_path):
    clip = make_clip(tmp_path / "a.mp4", seconds=3, size="320x180")
    frames = list(iter_frames(clip, 10))
    assert [t for t, _ in frames] == list(range(0, 3000, 100))
    assert frames[0][1].shape == (180, 320, 3)


def test_iter_frames_stops_early_without_hanging(tmp_path):
    clip = make_clip(tmp_path / "a.mp4", seconds=3, size="320x180")
    gen = iter_frames(clip, 10)
    next(gen)
    gen.close()


def _dims(path):
    info = probe(path)
    return info.width, info.height


def test_transcode_proxy_caps_height_and_never_upscales(tmp_path):
    big = make_clip(tmp_path / "big.mp4", seconds=1, size="1920x1080")
    out = tmp_path / "big_proxy.mp4"
    progress: list[float] = []
    transcode_proxy(big, out, on_progress=progress.append)
    assert _dims(out) == (1280, 720)
    assert not out.with_suffix(".tmp.mp4").exists()
    assert progress and all(0 <= p <= 1 for p in progress)

    small = make_clip(tmp_path / "small.mp4", seconds=1, size="640x360")
    out2 = tmp_path / "small_proxy.mp4"
    transcode_proxy(small, out2)
    assert _dims(out2) == (640, 360)


def test_transcode_proxy_failure_raises_and_leaves_no_tmp(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_text("nope")
    out = tmp_path / "o.mp4"
    with pytest.raises(VideoError):
        transcode_proxy(bad, out)
    assert not out.exists() and not out.with_suffix(".tmp.mp4").exists()


def test_extract_frame_writes_jpeg(tmp_path):
    clip = make_clip(tmp_path / "a.mp4", seconds=2)
    dest = tmp_path / "f.jpg"
    extract_frame(clip, 1000, dest)
    assert dest.read_bytes().startswith(b"\xff\xd8")


def test_extract_frame_failure_raises(tmp_path):
    with pytest.raises(VideoError):
        extract_frame(tmp_path / "missing.mp4", 0, tmp_path / "f.jpg")

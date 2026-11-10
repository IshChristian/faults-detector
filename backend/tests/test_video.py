import os
import subprocess
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


def _fake_ffmpeg(tmp_path, monkeypatch, body: str):
    """Put a fake `ffmpeg` first on PATH (ffprobe stays real)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "ffmpeg"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")


def test_iter_frames_raises_when_ffmpeg_fails_mid_stream(tmp_path, monkeypatch):
    clip = make_clip(tmp_path / "a.mp4", seconds=1, size="320x180")
    # One full 320x180 BGR frame, then a decode error and a non-zero exit.
    _fake_ffmpeg(tmp_path, monkeypatch, "head -c 172800 /dev/zero\necho 'boom: decode failed' >&2\nexit 1\n")
    seen = []
    with pytest.raises(VideoError, match="boom: decode failed"):
        for item in iter_frames(clip, 10):
            seen.append(item)
    assert len(seen) == 1


def test_iter_frames_early_close_does_not_raise_on_ffmpeg_failure(tmp_path, monkeypatch):
    clip = make_clip(tmp_path / "a.mp4", seconds=1, size="320x180")
    _fake_ffmpeg(tmp_path, monkeypatch, "head -c 172800 /dev/zero\nsleep 5\nexit 1\n")
    gen = iter_frames(clip, 10)
    next(gen)
    gen.close()  # consumer stopped early: ffmpeg is killed silently


def test_iter_frames_on_truncated_mp4_yields_fewer_frames_without_error(tmp_path):
    """iter_frames cannot detect truncation; the check lives in the processing job
    (app.worker.session_jobs compares analysed frames with duration * sample_fps)."""
    # Documents ffmpeg's behaviour: a truncated mp4 (moov at the front, so it still probes) makes ffmpeg
    # log "partial file" but exit 0, so iter_frames cannot tell it from a normal short video.
    full = make_clip(tmp_path / "full.mp4", seconds=3, size="320x180")
    faststart = tmp_path / "fs.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(full), "-c", "copy",
         "-movflags", "+faststart", str(faststart)],
        check=True,
    )  # fmt: skip
    cut = tmp_path / "cut.mp4"
    cut.write_bytes(faststart.read_bytes()[: faststart.stat().st_size // 2])
    frames = list(iter_frames(cut, 10))
    assert 0 < len(frames) < 30

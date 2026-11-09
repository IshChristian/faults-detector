"""Thin wrappers around ffprobe/ffmpeg used by uploads, calibration and tracking.

ffmpeg autorotates by display matrix / rotate tag, so frames and proxies come
out in display orientation; `probe` reports display dimensions to match.
"""

import json
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np


class VideoError(Exception):
    pass


@dataclass(frozen=True)
class VideoInfo:
    duration_ms: int
    fps: float
    width: int
    height: int
    creation_time: datetime | None
    codec: str


def _parse_rate(value: str | None) -> float:
    if not value:
        return 0.0
    num, _, den = value.partition("/")
    try:
        d = float(den) if den else 1.0
        return float(num) / d if d else 0.0
    except ValueError:
        return 0.0


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _rotation(stream: dict) -> int:
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            return int(round(float(side["rotation"])))
    try:
        return int(round(float((stream.get("tags") or {}).get("rotate", 0))))
    except ValueError:
        return 0


def probe(path: Path) -> VideoInfo:
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise VideoError("not a readable video") from exc
    if res.returncode != 0:
        raise VideoError("not a readable video")
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise VideoError("not a readable video") from exc
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if stream is None:
        raise VideoError("not a readable video")

    fmt = data.get("format", {})
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    if _rotation(stream) % 180 != 0:
        width, height = height, width
    duration = stream.get("duration")
    if duration in (None, "N/A"):
        duration = fmt.get("duration")
    try:
        duration_ms = round(float(duration) * 1000)
    except (TypeError, ValueError):
        duration_ms = 0
    fps = _parse_rate(stream.get("avg_frame_rate")) or _parse_rate(stream.get("r_frame_rate"))
    created = _parse_time((fmt.get("tags") or {}).get("creation_time")) or _parse_time(
        (stream.get("tags") or {}).get("creation_time")
    )
    return VideoInfo(
        duration_ms=duration_ms,
        fps=fps,
        width=width,
        height=height,
        creation_time=created,
        codec=stream.get("codec_name", ""),
    )


def _has_audio(src: Path) -> bool:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(src)],
        capture_output=True,
        text=True,
        check=False,
    )
    return res.returncode == 0 and bool(res.stdout.strip())


def transcode_proxy(src: Path, dest: Path, on_progress: Callable[[float], None] | None = None) -> None:
    info = probe(src)
    tmp = dest.with_suffix(".tmp.mp4")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(src),
        "-vf", "scale=-2:'min(720,ih)'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
    ]  # fmt: skip
    cmd += ["-c:a", "aac", "-b:a", "96k"] if _has_audio(src) else ["-an"]
    cmd += ["-movflags", "+faststart", "-f", "mp4", "-progress", "pipe:1", str(tmp)]

    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and on_progress and info.duration_ms > 0:
                    try:
                        us = int(value)
                    except ValueError:
                        continue
                    on_progress(min(1.0, max(0.0, us / (info.duration_ms * 1000))))
            code = proc.wait()
        except BaseException:
            proc.kill()
            proc.wait()
            tmp.unlink(missing_ok=True)
            raise
        if code != 0:
            err.seek(0)
            tmp.unlink(missing_ok=True)
            raise VideoError(f"transcode failed: {err.read().decode(errors='replace')[-500:]}")
    tmp.rename(dest)
    if on_progress:
        on_progress(1.0)


def extract_frame(src: Path, t_ms: int, dest: Path) -> None:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", f"{t_ms / 1000:.3f}", "-i", str(src),
        "-frames:v", "1", "-q:v", "3", str(dest),
    ]  # fmt: skip
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise VideoError(f"could not extract frame: {res.stderr[-500:]}")


def iter_frames(src: Path, sample_fps: float) -> Iterator[tuple[int, np.ndarray]]:
    info = probe(src)
    w, h = info.width, info.height
    size = w * h * 3
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(src), "-vf", f"fps={sample_fps}",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1",
    ]  # fmt: skip
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        assert proc.stdout is not None
        i = 0
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield round(i * 1000 / sample_fps), np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        if proc.poll() is None:
            proc.kill()
        if proc.stdout:
            proc.stdout.close()
        proc.wait()

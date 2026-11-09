"""Test helper that generates small synthetic clips with ffmpeg."""

import functools
import subprocess
from pathlib import Path


@functools.lru_cache(maxsize=1)
def _supports_display_rotation() -> bool:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-h", "full"], capture_output=True, text=True, check=False
    )
    return "display_rotation" in out.stdout + out.stderr


def make_clip(
    path: Path,
    seconds: float = 3,
    size: str = "640x360",
    fps: int = 25,
    creation_time: str | None = "2026-11-01T09:00:00Z",
    rotation: int | None = None,
) -> Path:
    """Write a testsrc2 H.264 clip. `rotation` marks display rotation metadata.

    Uses the `-display_rotation` input option when the installed ffmpeg has it
    (>= 6); otherwise remuxes the clip with `-metadata:s:v:0 rotate=N`, which
    ffmpeg 4.x's mp4 muxer only honours on a stream copy, not while encoding.
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    legacy_rotate = rotation is not None and not _supports_display_rotation()
    if rotation is not None and not legacy_rotate:
        cmd += ["-display_rotation", str(rotation)]
    cmd += ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if creation_time is not None:
        cmd += ["-metadata", f"creation_time={creation_time}"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    if legacy_rotate:
        tmp = path.with_suffix(".rot.mp4")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-c", "copy",
             "-metadata:s:v:0", f"rotate={rotation}", str(tmp)],
            check=True,
        )  # fmt: skip
        tmp.replace(path)
    return path

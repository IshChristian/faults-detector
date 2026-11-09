"""Staging area for in-flight uploads: {media_root}/_uploads/{video_id}.part.

Lives under media_root so the final move into storage stays on one filesystem (atomic rename).
The file's size on disk is the single source of truth for the tus offset.
"""
import os
import uuid
from pathlib import Path

from app.config import get_settings


def staging_path(video_id: uuid.UUID) -> Path:
    return Path(get_settings().media_root) / "_uploads" / f"{video_id}.part"


def create_staging(video_id: uuid.UUID) -> Path:
    path = staging_path(video_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def staged_size(video_id: uuid.UUID) -> int:
    try:
        return staging_path(video_id).stat().st_size
    except FileNotFoundError:
        return 0


def remove_staging(video_id: uuid.UUID) -> None:
    staging_path(video_id).unlink(missing_ok=True)


def fsync_file(f) -> None:
    f.flush()
    os.fsync(f.fileno())

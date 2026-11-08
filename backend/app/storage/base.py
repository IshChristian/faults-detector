"""Media storage interface. Keys are relative paths like clips/{customer_id}/2026/11/{id}.mp4."""
from pathlib import Path
from typing import BinaryIO, Protocol

from app.common.errors import ApiError
from app.config import get_settings


class Storage(Protocol):
    def save(self, key: str, data: BinaryIO) -> int: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def local_path(self, key: str) -> Path | None: ...


def validate_key(key: str) -> str:
    """Reject anything that could escape the storage root or be ambiguous."""
    bad = (
        not key
        or key.startswith("/")
        or "\\" in key
        or "\x00" in key
        or any(part in ("", ".", "..") for part in key.split("/"))
    )
    if bad:
        raise ApiError(400, "invalid-key", "Invalid media key")
    return key


def get_storage() -> Storage:
    """FastAPI dependency. Only the local backend exists in V1."""
    from app.storage.local import LocalStorage

    settings = get_settings()
    if settings.storage_backend == "local":
        return LocalStorage(settings.media_root)
    raise NotImplementedError(f"storage backend {settings.storage_backend!r} is not available yet")

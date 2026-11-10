import errno
import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from app.common.errors import ApiError
from app.config import get_settings
from app.storage.base import validate_key


def scratch_dir() -> tempfile.TemporaryDirectory:
    """A temporary directory under {media_root}/_tmp, so importing its files into storage is a same-filesystem
    rename (in Docker, /tmp is the container's filesystem and the media root is a separate volume)."""
    parent = Path(get_settings().media_root) / "_tmp"
    parent.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=parent)


class LocalStorage:
    """Files under one root directory (a Docker volume in production)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        if not path.is_relative_to(self.root):  # defence in depth, e.g. against symlinks
            raise ApiError(400, "invalid-key", "Invalid media key")
        return path

    def save(self, key: str, data: BinaryIO) -> int:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(data, out, length=1024 * 1024)
                size = out.tell()
            os.replace(tmp, path)  # atomic: readers never see a half-written file
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return size

    def import_file(self, key: str, src: Path) -> int:
        """Move `src` into the store and return its size. Readers never see a partial file: across filesystems
        `src` is copied to a temp file beside the destination, fsynced, then renamed into place."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        size = Path(src).stat().st_size
        try:
            os.replace(src, path)
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
            self._copy_into_place(Path(src), path)
            Path(src).unlink(missing_ok=True)
        return size

    @staticmethod
    def _copy_into_place(src: Path, path: Path) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as out, src.open("rb") as f:
                shutil.copyfileobj(f, out, length=1024 * 1024)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_matching(self, dir_key: str, pattern: str) -> None:
        """Delete the files directly under `dir_key` whose names match the glob `pattern`."""
        directory = self._path(dir_key)
        if directory.is_dir():
            for path in directory.glob(pattern):
                if path.is_file() and path.resolve().parent == directory:
                    path.unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def local_path(self, key: str) -> Path | None:
        return self._path(key)

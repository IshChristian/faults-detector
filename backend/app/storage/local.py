import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from app.common.errors import ApiError
from app.storage.base import validate_key


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
        """Move `src` into the store (atomic when on the same filesystem) and return its size."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        size = Path(src).stat().st_size
        os.replace(src, path)
        return size

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def local_path(self, key: str) -> Path | None:
        return self._path(key)

import io
from pathlib import Path
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.common.errors import ApiError
from app.main import create_app
from app.storage.base import get_storage, validate_key
from app.storage.local import LocalStorage
from app.storage.signing import sign_media_url, verify_media_signature


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


@pytest.fixture
async def media_client(storage):
    app = create_app()
    app.dependency_overrides[get_storage] = lambda: storage
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def test_local_save_open_roundtrip(storage):
    n = storage.save("clips/c1/2026/11/a.mp4", io.BytesIO(b"hello video"))
    assert n == 11
    assert storage.exists("clips/c1/2026/11/a.mp4")
    with storage.open("clips/c1/2026/11/a.mp4") as f:
        assert f.read() == b"hello video"
    assert storage.local_path("clips/c1/2026/11/a.mp4").read_bytes() == b"hello video"


def test_save_overwrites_atomically_without_leftovers(storage):
    storage.save("k/x.bin", io.BytesIO(b"one"))
    storage.save("k/x.bin", io.BytesIO(b"two"))
    assert storage.open("k/x.bin").read() == b"two"
    assert [p.name for p in storage.local_path("k/x.bin").parent.iterdir()] == ["x.bin"]


def test_delete_missing_is_noop(storage):
    storage.delete("never/existed.bin")
    storage.save("a.bin", io.BytesIO(b"x"))
    storage.delete("a.bin")
    assert not storage.exists("a.bin")


@pytest.mark.parametrize("key", ["../x", "a/../../x", "/etc/passwd", "a\\b", "", "a/\x00b", "a//b", "./a"])
def test_validate_key_rejects_traversal(key, storage):
    with pytest.raises(ApiError) as e:
        validate_key(key)
    assert e.value.status == 400 and e.value.slug == "invalid-key"
    with pytest.raises(ApiError):
        storage.save(key, io.BytesIO(b"x"))


def test_validate_key_accepts_normal_keys():
    assert validate_key("sessions/c/s/proxy/v.mp4") == "sessions/c/s/proxy/v.mp4"


def test_signature_verification():
    url = sign_media_url("a/b.jpg", ttl_seconds=60, now=1_000)
    exp = int(url.split("exp=")[1].split("&")[0])
    sig = url.split("sig=")[1]
    assert exp == 1_060
    assert verify_media_signature("a/b.jpg", exp, sig, now=1_059)
    assert not verify_media_signature("a/b.jpg", exp, sig, now=1_061)
    assert not verify_media_signature("a/c.jpg", exp, sig, now=1_000)
    assert not verify_media_signature("a/b.jpg", exp + 1, sig, now=1_000)


async def test_signed_url_serves_file(media_client, storage):
    storage.save("snaps/a.jpg", io.BytesIO(b"\xff\xd8jpegdata"))
    r = await media_client.get(sign_media_url("snaps/a.jpg"))
    assert r.status_code == 200
    assert r.content == b"\xff\xd8jpegdata"
    assert r.headers["content-type"] == "image/jpeg"


async def test_expired_signature_403(media_client, storage):
    storage.save("snaps/a.jpg", io.BytesIO(b"x"))
    url = sign_media_url("snaps/a.jpg", ttl_seconds=10, now=int(time.time()) - 100)
    r = await media_client.get(url)
    assert r.status_code == 403 and r.json()["type"].endswith("/invalid-signature")


async def test_tampered_key_403(media_client, storage):
    storage.save("snaps/a.jpg", io.BytesIO(b"a"))
    storage.save("snaps/b.jpg", io.BytesIO(b"b"))
    url = sign_media_url("snaps/a.jpg").replace("snaps/a.jpg", "snaps/b.jpg")
    assert (await media_client.get(url)).status_code == 403
    assert (await media_client.get("/api/v1/media/snaps/a.jpg")).status_code == 403


async def test_missing_file_with_valid_signature_404(media_client):
    assert (await media_client.get(sign_media_url("nope/x.mp4"))).status_code == 404


async def test_range_request_returns_206(media_client, storage):
    storage.save("v/clip.mp4", io.BytesIO(bytes(range(100))))
    r = await media_client.get(sign_media_url("v/clip.mp4"), headers={"Range": "bytes=10-19"})
    assert r.status_code == 206
    assert r.content == bytes(range(10, 20))
    assert r.headers["content-range"] == "bytes 10-19/100"


def test_import_file_falls_back_to_copy_across_filesystems(storage, tmp_path, monkeypatch):
    # In Docker /tmp and the media volume are separate filesystems: rename(2) fails with EXDEV.
    import errno
    import os

    import app.storage.local as local

    src = tmp_path / "elsewhere" / "proxy.mp4"
    src.parent.mkdir()
    src.write_bytes(b"proxy bytes")
    real_replace, calls = os.replace, []

    def replace(a, b):
        calls.append((a, b))
        if len(calls) == 1:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_replace(a, b)

    monkeypatch.setattr(local.os, "replace", replace)
    assert storage.import_file("sessions/c/s/proxy/v.mp4", src) == 11
    assert storage.open("sessions/c/s/proxy/v.mp4").read() == b"proxy bytes"
    assert not src.exists()
    dest_dir = storage.local_path("sessions/c/s/proxy/v.mp4").parent
    assert [p.name for p in dest_dir.iterdir()] == ["v.mp4"]  # no temp file left behind
    assert len(calls) == 2 and Path(calls[1][0]).parent == dest_dir  # the final step is an atomic same-dir rename


def test_import_file_reraises_other_os_errors(storage, tmp_path, monkeypatch):
    import errno

    import app.storage.local as local

    src = tmp_path / "x.bin"
    src.write_bytes(b"x")

    def replace(a, b):
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(local.os, "replace", replace)
    with pytest.raises(PermissionError):
        storage.import_file("a/x.bin", src)


def test_scratch_dir_is_under_media_root(storage, monkeypatch):
    from app.config import get_settings
    from app.storage.local import scratch_dir

    monkeypatch.setattr(get_settings(), "media_root", storage.root)
    with scratch_dir() as tmp:
        assert Path(tmp).is_relative_to(storage.root / "_tmp") and Path(tmp).is_dir()
    assert not Path(tmp).exists()

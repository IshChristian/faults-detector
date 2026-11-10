import base64
import uuid

from sqlalchemy import event, func, select, text

from app.models import AuditLog, Camera, Session, SessionVideo, Site
from tests.media import make_clip

TUS = {"Tus-Resumable": "1.0.0"}
PATCH_CT = {"Content-Type": "application/offset+octet-stream"}


def _meta(**kw) -> str:
    return ",".join(f"{k} {base64.b64encode(v.encode()).decode()}" for k, v in kw.items())


async def tus_create(client, headers, session_id, length, filename="clip.mp4"):
    return await client.post("/api/v1/uploads", headers={
        **headers, **TUS, "Upload-Length": str(length),
        "Upload-Metadata": _meta(session_id=str(session_id), filename=filename)})


async def tus_patch(client, headers, location, offset, data):
    return await client.patch(location, content=data, headers={
        **headers, **TUS, **PATCH_CT, "Upload-Offset": str(offset)})


async def tus_upload(client, headers, session_id, data: bytes, chunk: int | None = None, filename="clip.mp4"):
    """Drive POST then PATCH in chunks; returns the last PATCH response."""
    created = await tus_create(client, headers, session_id, len(data), filename)
    assert created.status_code == 201, created.text
    location = created.headers["Location"]
    chunk = chunk or len(data)
    offset, resp = 0, None
    while offset < len(data):
        resp = await tus_patch(client, headers, location, offset, data[offset:offset + chunk])
        if resp.status_code != 204:
            break
        offset = int(resp.headers["Upload-Offset"])
    resp.location = location
    return resp


async def _session(client, db_session, tenant, role="operator"):
    customer, user, headers = await tenant(role)
    site = Site(customer_id=customer.id, name="Pitch", timezone="Africa/Kigali")
    db_session.add(site)
    await db_session.flush()
    cam = Camera(customer_id=customer.id, site_id=site.id, name="Phone", mode="upload", source_type="file")
    db_session.add(cam)
    await db_session.flush()
    r = await client.post("/api/v1/sessions", headers=headers, json={
        "site_id": str(site.id), "source_id": str(cam.id), "type": "training", "starts_at": "2026-11-01T09:00:00Z"})
    return r.json()["id"], headers


async def _videos(db_session, sid):
    await db_session.flush()
    db_session.expire_all()
    rows = await db_session.execute(
        select(SessionVideo).where(SessionVideo.session_id == uuid.UUID(sid)).order_by(SessionVideo.position))
    return list(rows.scalars())


async def test_options_advertises_tus_and_max_size(client):
    r = await client.options("/api/v1/uploads")
    assert r.status_code == 204
    assert r.headers["Tus-Version"] == "1.0.0" and r.headers["Tus-Resumable"] == "1.0.0"
    assert r.headers["Tus-Extension"] == "creation,termination"
    assert r.headers["Tus-Max-Size"] == str(10 * 1024**3)


async def test_full_upload_in_chunks_stores_original_and_probes(client, db_session, tenant, tmp_path, media_storage):
    sid, headers = await _session(client, db_session, tenant)
    data = make_clip(tmp_path / "a.mp4", seconds=2).read_bytes()
    third = len(data) // 3 + 1
    r = await tus_upload(client, headers, sid, data, chunk=third, filename="Drill 1.mp4")
    assert r.status_code == 204 and r.headers["Upload-Offset"] == str(len(data))
    (video,) = await _videos(db_session, sid)
    assert video.status == "uploaded" and video.original_filename == "Drill 1.mp4"
    assert video.size_bytes == len(data) and video.position == 0
    assert media_storage.exists(video.original_key)
    assert video.original_key.endswith(f"/source/{video.id}.mp4") and video.original_key.startswith("sessions/")
    assert abs(video.duration_ms - 2000) < 200 and float(video.fps) == 25.0
    assert (video.width, video.height) == (640, 360) and video.creation_time is not None
    assert not (media_storage.root / "_uploads" / f"{video.id}.part").exists()
    detail = (await client.get(f"/api/v1/sessions/{sid}", headers=headers)).json()
    assert detail["videos"][0]["status"] == "uploaded" and "original_key" not in detail["videos"][0]


async def test_upload_length_over_10_gib_is_413(client, db_session, tenant):
    sid, headers = await _session(client, db_session, tenant)
    r = await tus_create(client, headers, sid, 10 * 1024**3 + 1)
    assert r.status_code == 413 and r.json()["type"].endswith("/too-large")
    assert r.headers["Tus-Resumable"] == "1.0.0"


async def test_missing_session_id_metadata_is_422(client, db_session, tenant):
    _, headers = await _session(client, db_session, tenant)
    r = await client.post("/api/v1/uploads", headers={**headers, **TUS, "Upload-Length": "10",
                                                      "Upload-Metadata": _meta(filename="x.mp4")})
    assert r.status_code == 422 and r.json()["type"].endswith("/validation")


async def test_patch_with_wrong_offset_is_409(client, db_session, tenant):
    sid, headers = await _session(client, db_session, tenant)
    loc = (await tus_create(client, headers, sid, 100)).headers["Location"]
    r = await tus_patch(client, headers, loc, 5, b"x" * 10)
    assert r.status_code == 409 and r.json()["type"].endswith("/offset-mismatch")


async def test_patch_past_upload_length_is_400_and_keeps_nothing_extra(client, db_session, tenant, media_storage):
    sid, headers = await _session(client, db_session, tenant)
    loc = (await tus_create(client, headers, sid, 10)).headers["Location"]
    r = await tus_patch(client, headers, loc, 0, b"x" * 11)
    assert r.status_code == 400
    head = await client.head(loc, headers={**headers, **TUS})
    assert head.headers["Upload-Offset"] == "0"


async def test_head_reports_bytes_on_disk_after_interrupted_patch(client, db_session, tenant, tmp_path, media_storage):
    sid, headers = await _session(client, db_session, tenant)
    data = make_clip(tmp_path / "a.mp4", seconds=1).read_bytes()
    loc = (await tus_create(client, headers, sid, len(data))).headers["Location"]
    part = media_storage.root / "_uploads" / f"{loc.rsplit('/', 1)[1]}.part"
    with part.open("ab") as f:  # a PATCH that died after writing 1000 bytes
        f.write(data[:1000])
    head = await client.head(loc, headers={**headers, **TUS})
    assert head.status_code == 200 and head.headers["Upload-Offset"] == "1000"
    assert head.headers["Upload-Length"] == str(len(data)) and head.headers["Cache-Control"] == "no-store"
    r = await tus_patch(client, headers, loc, 1000, data[1000:])
    assert r.status_code == 204 and r.headers["Upload-Offset"] == str(len(data))
    assert (await _videos(db_session, sid))[0].status == "uploaded"


async def test_missing_tus_resumable_header_is_412(client, db_session, tenant):
    sid, headers = await _session(client, db_session, tenant)
    r = await client.post("/api/v1/uploads", headers={**headers, "Upload-Length": "5",
                                                      "Upload-Metadata": _meta(session_id=sid)})
    assert r.status_code == 412 and r.headers["Tus-Resumable"] == "1.0.0"


async def test_videos_without_creation_time_order_after_timed_ones(client, db_session, tenant, tmp_path):
    sid, headers = await _session(client, db_session, tenant)
    for name, ts in (("A", None), ("B", "2026-11-01T10:00:00Z"), ("C", "2026-11-01T09:00:00Z")):
        clip = make_clip(tmp_path / f"{name}.mp4", seconds=1, creation_time=ts)
        r = await tus_upload(client, headers, sid, clip.read_bytes(), filename=f"{name}.mp4")
        assert r.status_code == 204
    assert [v.original_filename for v in await _videos(db_session, sid)] == ["C.mp4", "B.mp4", "A.mp4"]
    assert [v.position for v in await _videos(db_session, sid)] == [0, 1, 2]


async def test_non_video_upload_is_marked_failed_and_blocks_processing(client, db_session, tenant, tmp_path,
                                                                       media_storage):
    sid, headers = await _session(client, db_session, tenant)
    good = make_clip(tmp_path / "g.mp4", seconds=1).read_bytes()
    assert (await tus_upload(client, headers, sid, good)).status_code == 204
    bad = await tus_upload(client, headers, sid, b"this is not a video" * 50, filename="notes.mp4")
    assert bad.status_code == 422 and bad.json()["type"].endswith("/not-a-video")
    failed = [v for v in await _videos(db_session, sid) if v.status == "failed"]
    assert len(failed) == 1 and failed[0].error == "This file isn't a readable video."
    assert not (media_storage.root / "_uploads" / f"{failed[0].id}.part").exists()
    process = f"/api/v1/sessions/{sid}/process"
    assert (await client.post(process, headers=headers)).status_code == 422
    assert (await client.delete(bad.location, headers={**headers, **TUS})).status_code == 204
    assert (await client.post(process, headers=headers)).status_code == 202


async def test_other_customers_upload_is_404(client, db_session, tenant):
    sid, headers = await _session(client, db_session, tenant)
    loc = (await tus_create(client, headers, sid, 100)).headers["Location"]
    _, _, other = await tenant("operator")
    assert (await client.head(loc, headers={**other, **TUS})).status_code == 404
    assert (await tus_patch(client, other, loc, 0, b"x")).status_code == 404
    assert (await client.delete(loc, headers={**other, **TUS})).status_code == 404
    assert (await tus_create(client, other, sid, 100)).status_code == 404


async def test_delete_upload_renumbers_positions(client, db_session, tenant, tmp_path, media_storage):
    sid, headers = await _session(client, db_session, tenant)
    locs = []
    for i in range(3):
        clip = make_clip(tmp_path / f"{i}.mp4", seconds=1, creation_time=f"2026-11-01T0{i}:00:00Z")
        locs.append((await tus_upload(client, headers, sid, clip.read_bytes())).location)
    first, middle, last = await _videos(db_session, sid)
    assert media_storage.exists(middle.original_key)
    assert (await client.delete(locs[1], headers={**headers, **TUS})).status_code == 204
    rest = await _videos(db_session, sid)
    assert [(v.id, v.position) for v in rest] == [(first.id, 0), (last.id, 1)]
    assert not media_storage.exists(middle.original_key)
    db_session.expire_all()
    audit = (await db_session.execute(select(AuditLog).where(AuditLog.action == "session.video_delete"))).scalar_one()
    assert audit.entity_id == uuid.UUID(sid)
    assert audit.details == {"video_id": str(middle.id), "filename": "clip.mp4"}


async def test_delete_uploaded_video_blocked_while_queued(client, db_session, tenant, tmp_path):
    sid, headers = await _session(client, db_session, tenant)
    r = await tus_upload(client, headers, sid, make_clip(tmp_path / "a.mp4", seconds=1).read_bytes())
    assert (await client.post(f"/api/v1/sessions/{sid}/process", headers=headers)).status_code == 202
    assert (await client.delete(r.location, headers={**headers, **TUS})).status_code == 409
    session = await db_session.get(Session, uuid.UUID(sid))
    assert session.status == "queued"


async def test_two_uploads_in_progress_one_completes_while_other_is_mid_upload(
        client, db_session, tenant, tmp_path):
    """One test client shares a single DB connection, so true parallelism is impossible here. Instead:
    B is mid-upload when A completes (reordering B's row), then B completes. Statements are captured to prove
    PATCH never row-locks a video before the session row, the ordering that prevents the A/B deadlock."""
    sid, headers = await _session(client, db_session, tenant)
    a = make_clip(tmp_path / "a.mp4", seconds=1, creation_time="2026-11-01T10:00:00Z").read_bytes()
    b = make_clip(tmp_path / "b.mp4", seconds=1, creation_time="2026-11-01T09:00:00Z").read_bytes()
    loc_b = (await tus_create(client, headers, sid, len(b), "b.mp4")).headers["Location"]
    loc_a = (await tus_create(client, headers, sid, len(a), "a.mp4")).headers["Location"]
    assert (await tus_patch(client, headers, loc_b, 0, b[:1000])).status_code == 204  # B in progress

    statements: list[str] = []
    engine = db_session.bind.sync_engine if hasattr(db_session.bind, "sync_engine") else db_session.sync_session.bind
    listener = lambda conn, cur, stmt, *args: statements.append(stmt)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        assert (await tus_patch(client, headers, loc_a, 0, a)).status_code == 204  # A completes
        assert (await tus_patch(client, headers, loc_b, 1000, b[1000:])).status_code == 204  # then B
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    locking = [st for st in statements if "FOR UPDATE" in st]
    assert locking and all("FROM sessions" in st and "session_videos" not in st for st in locking)
    videos = await _videos(db_session, sid)
    assert [(v.original_filename, v.status, v.position) for v in videos] == [
        ("b.mp4", "uploaded", 0), ("a.mp4", "uploaded", 1)]


async def test_delete_is_409_while_another_transaction_holds_the_upload_lock(client, db_session, tenant, engine):
    sid, headers = await _session(client, db_session, tenant)
    loc = (await tus_create(client, headers, sid, 100)).headers["Location"]
    video_id = loc.rsplit("/", 1)[1]
    key = text("hashtextextended(:id, 0)")
    async with engine.connect() as other:  # a second connection plays the in-flight PATCH
        await other.execute(select(func.pg_advisory_lock(key.bindparams(id=video_id))))
        r = await client.delete(loc, headers={**headers, **TUS})
        assert r.status_code == 409 and r.json()["type"].endswith("/conflict")
        assert len(await _videos(db_session, sid)) == 1
        await other.execute(select(func.pg_advisory_unlock(key.bindparams(id=video_id))))
        await other.rollback()
    assert (await client.delete(loc, headers={**headers, **TUS})).status_code == 204
    assert await _videos(db_session, sid) == []

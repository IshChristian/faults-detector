from sqlalchemy import select

from app.models import Camera
from app.security.crypto import decrypt_secret

RTSP = "rtsp://frigate:secret@192.168.1.10:554/Streaming/Channels/101"


async def _site(client, h, name="Pitch"):
    return (await client.post("/api/v1/sites", json={"name": name}, headers=h)).json()


async def test_live_camera_requires_frigate_name(client, tenant):
    _, _, h = await tenant()
    site = await _site(client, h)
    r = await client.post("/api/v1/cameras", json={"site_id": site["id"], "name": "Gate", "mode": "live",
                                                   "source_type": "rtsp"}, headers=h)
    assert r.status_code == 422


async def test_upload_camera_without_frigate_name_ok(client, tenant):
    c, _, h = await tenant()
    site = await _site(client, h)
    r = await client.post("/api/v1/cameras", json={"site_id": site["id"], "name": "Halfway line", "mode": "upload",
                                                   "source_type": "phone"}, headers=h)
    assert r.status_code == 201
    body = r.json()
    assert body["mode"] == "upload" and body["customer_id"] == str(c.id) and body["source_url_set"] is False


async def test_source_url_is_encrypted_and_never_returned(client, db_session, tenant):
    _, _, h = await tenant()
    site = await _site(client, h)
    created = await client.post("/api/v1/cameras", json={
        "site_id": site["id"], "name": "Gate", "mode": "live", "frigate_name": "gate",
        "source_type": "rtsp", "source_url": RTSP}, headers=h)
    assert created.status_code == 201
    cam_id = created.json()["id"]
    raw = (await db_session.execute(select(Camera.source_url_encrypted).where(Camera.id == cam_id))).scalar_one()
    assert RTSP.encode() not in raw and decrypt_secret(raw) == RTSP
    one = await client.get(f"/api/v1/cameras/{cam_id}", headers=h)
    listing = await client.get("/api/v1/cameras", headers=h)
    for r in (created, one, listing):
        assert "secret" not in r.text and '"source_url"' not in r.text
    assert one.json()["source_url_set"] is True and listing.json()["items"][0]["source_url_set"] is True


async def test_camera_on_other_customers_site_is_404(client, tenant):
    _, _, h_a = await tenant()
    _, _, h_b = await tenant()
    site_b = await _site(client, h_b)
    r = await client.post("/api/v1/cameras", json={"site_id": site_b["id"], "name": "x", "mode": "upload",
                                                   "source_type": "file"}, headers=h_a)
    assert r.status_code == 404


async def test_other_customers_camera_is_404_and_not_listed(client, tenant):
    _, _, h_a = await tenant()
    _, _, h_b = await tenant()
    site_b = await _site(client, h_b)
    cam = (await client.post("/api/v1/cameras", json={"site_id": site_b["id"], "name": "x", "mode": "upload",
                                                      "source_type": "file"}, headers=h_b)).json()
    url = f"/api/v1/cameras/{cam['id']}"
    assert (await client.get(url, headers=h_a)).status_code == 404
    assert (await client.patch(url, json={"name": "y"}, headers=h_a)).status_code == 404
    assert (await client.delete(url, headers=h_a)).status_code == 404
    assert (await client.get("/api/v1/cameras", headers=h_a)).json()["items"] == []


async def test_filter_by_site_and_mode(client, tenant):
    _, _, h = await tenant()
    s1, s2 = await _site(client, h, "One"), await _site(client, h, "Two")
    await client.post("/api/v1/cameras", json={"site_id": s1["id"], "name": "a", "mode": "upload", "source_type": "phone"}, headers=h)
    await client.post("/api/v1/cameras", json={"site_id": s2["id"], "name": "b", "mode": "live", "frigate_name": "b", "source_type": "rtsp"}, headers=h)
    by_site = (await client.get(f"/api/v1/cameras?site_id={s1['id']}", headers=h)).json()["items"]
    by_mode = (await client.get("/api/v1/cameras?mode=live", headers=h)).json()["items"]
    assert [c["name"] for c in by_site] == ["a"] and [c["name"] for c in by_mode] == ["b"]


async def test_patch_to_live_without_frigate_name_is_422(client, tenant):
    _, _, h = await tenant()
    site = await _site(client, h)
    cam = (await client.post("/api/v1/cameras", json={"site_id": site["id"], "name": "a", "mode": "upload",
                                                      "source_type": "phone"}, headers=h)).json()
    r = await client.patch(f"/api/v1/cameras/{cam['id']}", json={"mode": "live"}, headers=h)
    assert r.status_code == 422


async def test_duplicate_camera_name_on_site_is_409(client, tenant):
    _, _, h = await tenant()
    site = await _site(client, h)
    body = {"site_id": site["id"], "name": "Gate", "mode": "upload", "source_type": "file"}
    assert (await client.post("/api/v1/cameras", json=body, headers=h)).status_code == 201
    assert (await client.post("/api/v1/cameras", json=body, headers=h)).status_code == 409


async def test_viewer_cannot_create_camera(client, tenant, make_user, auth_headers):
    c, _, h = await tenant()
    site = await _site(client, h)
    viewer = auth_headers(await make_user(c, "viewer"))
    r = await client.post("/api/v1/cameras", json={"site_id": site["id"], "name": "a", "mode": "upload",
                                                   "source_type": "file"}, headers=viewer)
    assert r.status_code == 403


async def test_operator_can_add_an_upload_camera_and_it_is_audited(client, db_session, tenant, make_user,
                                                                   auth_headers):
    # A Coach adds a pitch position while creating a session.
    from app.models import AuditLog

    c, _, h = await tenant()
    site = await _site(client, h)
    coach = await make_user(c, "operator")
    r = await client.post("/api/v1/cameras", json={"site_id": site["id"], "name": "Halfway line", "mode": "upload",
                                                   "source_type": "phone"}, headers=auth_headers(coach))
    assert r.status_code == 201, r.text
    audit = (await db_session.execute(select(AuditLog).where(
        AuditLog.action == "camera.create", AuditLog.entity_id == r.json()["id"]))).scalar_one()
    assert audit.actor_user_id == coach.id


async def test_operator_cannot_add_a_live_camera(client, tenant, make_user, auth_headers):
    c, _, h = await tenant()
    site = await _site(client, h)
    coach = auth_headers(await make_user(c, "operator"))
    r = await client.post("/api/v1/cameras", json={"site_id": site["id"], "name": "Gate", "mode": "live",
                                                   "frigate_name": "gate", "source_type": "rtsp"}, headers=coach)
    assert r.status_code == 403

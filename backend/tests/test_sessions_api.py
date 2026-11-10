import uuid

from sqlalchemy import select

from app.models import AuditLog, Camera, Site
from tests.media import make_clip
from tests.test_uploads import tus_upload


async def _site_with_camera(db_session, customer, mode="upload"):
    site = Site(customer_id=customer.id, name="Pitch", timezone="Africa/Kigali")
    db_session.add(site)
    await db_session.flush()
    cam = Camera(customer_id=customer.id, site_id=site.id, name="Phone", mode=mode, source_type="file",
                 frigate_name="f" if mode == "live" else None)
    db_session.add(cam)
    await db_session.flush()
    return site, cam


def _body(site, cam, **kw):
    return {"site_id": str(site.id), "source_id": str(cam.id), "type": "training",
            "starts_at": "2026-11-01T09:00:00Z", **kw}


async def _create(client, headers, site, cam, **kw):
    r = await client.post("/api/v1/sessions", json=_body(site, cam, **kw), headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_operator_creates_session_on_upload_source(client, db_session, tenant):
    customer, _, headers = await tenant("operator")
    site, cam = await _site_with_camera(db_session, customer)
    data = await _create(client, headers, site, cam, title="Tuesday", squad="U17")
    assert data["status"] == "uploading" and data["customer_id"] == str(customer.id)
    assert data["videos"] == [] and data["title"] == "Tuesday"
    got = await client.get(f"/api/v1/sessions/{data['id']}", headers=headers)
    assert got.status_code == 200 and got.json()["id"] == data["id"]


async def test_source_must_be_upload_mode_on_same_site(client, db_session, tenant):
    customer, _, headers = await tenant("customer_admin")
    site, _cam = await _site_with_camera(db_session, customer)
    _, live = await _site_with_camera(db_session, customer, mode="live")
    other_site, other_cam = await _site_with_camera(db_session, customer)
    r = await client.post("/api/v1/sessions", json=_body(site, live), headers=headers)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "source_id"
    r = await client.post("/api/v1/sessions", json=_body(site, other_cam), headers=headers)
    assert r.status_code == 422 and r.json()["type"].endswith("/validation")
    assert other_site.id != site.id


async def test_viewer_cannot_create_or_process(client, db_session, tenant, make_user, auth_headers):
    customer, _, op_headers = await tenant("operator")
    site, cam = await _site_with_camera(db_session, customer)
    sid = (await _create(client, op_headers, site, cam))["id"]
    viewer = auth_headers(await make_user(customer, "viewer"))
    assert (await client.post("/api/v1/sessions", json=_body(site, cam), headers=viewer)).status_code == 403
    assert (await client.post(f"/api/v1/sessions/{sid}/process", headers=viewer)).status_code == 403
    assert (await client.get(f"/api/v1/sessions/{sid}", headers=viewer)).status_code == 200


async def test_other_customers_session_is_404(client, db_session, tenant):
    customer, _, headers = await tenant("operator")
    site, cam = await _site_with_camera(db_session, customer)
    sid = (await _create(client, headers, site, cam))["id"]
    _, _, other = await tenant("customer_admin")
    base = f"/api/v1/sessions/{sid}"
    assert (await client.get(base, headers=other)).status_code == 404
    assert (await client.patch(base, json={"title": "x"}, headers=other)).status_code == 404
    assert (await client.post(f"{base}/process", headers=other)).status_code == 404
    assert (await client.put(f"{base}/video-order", json={"video_ids": []}, headers=other)).status_code == 404
    r = await client.post("/api/v1/sessions", json=_body(site, cam), headers=other)
    assert r.status_code == 404


async def test_list_filters_by_site_and_status(client, db_session, tenant):
    customer, _, headers = await tenant("operator")
    site1, cam1 = await _site_with_camera(db_session, customer)
    site2, cam2 = await _site_with_camera(db_session, customer)
    a = await _create(client, headers, site1, cam1)
    await _create(client, headers, site2, cam2)
    r = await client.get(f"/api/v1/sessions?site_id={site1.id}", headers=headers)
    assert [i["id"] for i in r.json()["items"]] == [a["id"]]
    r = await client.get("/api/v1/sessions?status=ready", headers=headers)
    assert r.json()["items"] == []
    r = await client.get("/api/v1/sessions?status=uploading", headers=headers)
    assert len(r.json()["items"]) == 2


async def test_process_requires_uploaded_videos_and_enqueues(client, db_session, tenant, tmp_path, sessions_queue):
    customer, _, headers = await tenant("operator")
    site, cam = await _site_with_camera(db_session, customer)
    sid = (await _create(client, headers, site, cam))["id"]
    r = await client.post(f"/api/v1/sessions/{sid}/process", headers=headers)
    assert r.status_code == 422 and r.json()["type"].endswith("/not-processable")
    clip = make_clip(tmp_path / "a.mp4", seconds=1)
    await tus_upload(client, headers, sid, clip.read_bytes())
    r = await client.post(f"/api/v1/sessions/{sid}/process", headers=headers)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    jobs = sessions_queue.jobs
    assert len(jobs) == 1 and jobs[0].func_name == "app.worker.session_jobs.process_session"
    assert jobs[0].args == (sid,)


async def test_video_order_must_be_a_permutation(client, db_session, tenant, tmp_path):
    customer, _, headers = await tenant("operator")
    site, cam = await _site_with_camera(db_session, customer)
    sid = (await _create(client, headers, site, cam))["id"]
    for name, ts in (("a", "2026-11-01T09:00:00Z"), ("b", "2026-11-01T10:00:00Z")):
        await tus_upload(client, headers, sid, make_clip(tmp_path / f"{name}.mp4", seconds=1, creation_time=ts).read_bytes())
    videos = (await client.get(f"/api/v1/sessions/{sid}", headers=headers)).json()["videos"]
    ids = [v["id"] for v in videos]
    url = f"/api/v1/sessions/{sid}/video-order"
    assert (await client.put(url, json={"video_ids": ids[:1]}, headers=headers)).status_code == 422
    assert (await client.put(url, json={"video_ids": [*ids, str(uuid.uuid4())]}, headers=headers)).status_code == 422
    assert (await client.put(url, json={"video_ids": [ids[0], ids[0]]}, headers=headers)).status_code == 422
    r = await client.put(url, json={"video_ids": ids[::-1]}, headers=headers)
    assert r.status_code == 200 and [v["id"] for v in r.json()["videos"]] == ids[::-1]
    db_session.expire_all()
    audit = (await db_session.execute(select(AuditLog).where(AuditLog.action == "session.reorder"))).scalar_one()
    assert audit.entity_id == uuid.UUID(sid) and audit.details == {"video_ids": ids[::-1]}
    again = (await client.get(f"/api/v1/sessions/{sid}", headers=headers)).json()["videos"]
    assert [v["id"] for v in again] == ids[::-1]


async def test_sprint_threshold_change_enqueues_metrics_unless_uploading_or_uncalibrated(
        client, db_session, tenant, sessions_queue):
    from app.models import Calibration, Session

    customer, _, headers = await tenant("operator")
    site, cam = await _site_with_camera(db_session, customer)
    sid = (await _create(client, headers, site, cam))["id"]
    s = await db_session.get(Session, uuid.UUID(sid))
    url = f"/api/v1/sessions/{sid}"
    s.status = "ready"
    await db_session.flush()
    assert (await client.patch(url, json={"sprint_threshold_kmh": 20}, headers=headers)).status_code == 200
    assert sessions_queue.jobs == []  # uncalibrated: nothing to recompute
    cal = Calibration(customer_id=customer.id, camera_id=cam.id, image_points=[], pitch_points=[],
                      pitch_length_m=100, pitch_width_m=64)
    db_session.add(cal)
    await db_session.flush()
    s.calibration_id, s.status = cal.id, "uploading"
    await db_session.flush()
    assert (await client.patch(url, json={"sprint_threshold_kmh": 21}, headers=headers)).status_code == 200
    assert sessions_queue.jobs == []  # nothing processed yet: the first run uses the new threshold
    for i, status in enumerate(("queued", "processing", "ready")):
        s.status = status
        await db_session.flush()
        assert (await client.patch(url, json={"sprint_threshold_kmh": 22 + i}, headers=headers)).status_code == 200
    assert [j.func_name for j in sessions_queue.jobs] == ["app.worker.session_jobs.compute_session_metrics"] * 3

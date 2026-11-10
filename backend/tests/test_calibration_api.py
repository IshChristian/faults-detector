import uuid
from datetime import timedelta

from sqlalchemy import select

from app.models import AuditLog, Calibration, Session, SessionVideo
from tests.media import make_clip
from tests.test_sessions_api import _create, _site_with_camera
from tests.test_uploads import tus_upload

IMG = [[0.1, 0.9], [0.9, 0.9], [0.7, 0.3], [0.3, 0.3]]
LANDMARK_NAMES = ["corner_near_left", "corner_near_right", "corner_far_right", "corner_far_left"]
PITCH = [[0, 0], [100, 0], [100, 64], [0, 64]]


async def _session(client, db_session, tenant, role="operator"):
    customer, _, headers = await tenant(role)
    site, cam = await _site_with_camera(db_session, customer)
    data = await _create(client, headers, site, cam)
    return customer, site, cam, data["id"], headers


async def _calibrate(client, headers, sid, **kw):
    body = kw or {"image_points": IMG, "landmarks": LANDMARK_NAMES}
    return await client.post(f"/api/v1/sessions/{sid}/calibration", json=body, headers=headers)


async def test_save_calibration_with_landmarks_sets_session_calibration(client, db_session, tenant):
    customer, _, cam, sid, headers = await _session(client, db_session, tenant)
    r = await _calibrate(client, headers, sid, image_points=IMG, landmarks=LANDMARK_NAMES,
                         pitch_length_m=90, pitch_width_m=60)
    assert r.status_code == 201, r.text
    data = r.json()
    cal = data["calibration"]
    assert data["session"]["calibration_id"] == cal["id"]
    assert cal["camera_id"] == str(cam.id)
    assert cal["pitch_points"] == [[0, 0], [90, 0], [90, 60], [0, 60]]
    assert cal["image_points"] == IMG and cal["pitch_length_m"] == 90
    actions = (await db_session.execute(select(AuditLog.action).where(AuditLog.entity_id == uuid.UUID(sid)))).scalars()
    assert "calibration.save" in list(actions)


async def test_save_calibration_with_explicit_pitch_points(client, db_session, tenant):
    _, _, _, sid, headers = await _session(client, db_session, tenant)
    r = await _calibrate(client, headers, sid, image_points=IMG, pitch_points=PITCH)
    assert r.status_code == 201 and r.json()["calibration"]["pitch_points"] == PITCH


async def test_landmarks_xor_pitch_points_and_unknown_landmark_are_422(client, db_session, tenant):
    _, _, _, sid, headers = await _session(client, db_session, tenant)
    for body in (
        {"image_points": IMG},
        {"image_points": IMG, "landmarks": LANDMARK_NAMES, "pitch_points": PITCH},
        {"image_points": IMG, "landmarks": ["corner_near_left", "nope", "corner_far_right", "corner_far_left"]},
        {},
    ):
        r = await client.post(f"/api/v1/sessions/{sid}/calibration", json=body, headers=headers)
        assert r.status_code == 422 and r.json()["type"].endswith("/validation"), body


async def test_collinear_or_bowtie_points_are_422(client, db_session, tenant):
    _, _, _, sid, headers = await _session(client, db_session, tenant)
    r = await _calibrate(client, headers, sid, image_points=[[0.1, 0.5], [0.5, 0.5], [0.9, 0.5], [0.5, 0.1]],
                         landmarks=LANDMARK_NAMES)
    assert r.status_code == 422 and r.json()["type"].endswith("/invalid-calibration")
    assert "on one line" in r.json()["detail"]
    r = await _calibrate(client, headers, sid, image_points=[[0.1, 0.9], [0.9, 0.9], [0.3, 0.3], [0.7, 0.3]],
                         landmarks=LANDMARK_NAMES)
    assert r.status_code == 422 and r.json()["type"].endswith("/invalid-calibration")
    assert "cross over" in r.json()["detail"]
    r = await _calibrate(client, headers, sid, image_points=[[0.1, 0.9], [1.9, 0.9], [0.7, 0.3], [0.3, 0.3]],
                         landmarks=LANDMARK_NAMES)
    assert r.status_code == 422 and "inside the frame" in r.json()["detail"]
    r = await _calibrate(client, headers, sid, image_points=IMG[:3], landmarks=LANDMARK_NAMES[:3])
    assert r.status_code == 422 and "Exactly 4" in r.json()["detail"]


async def test_reuse_previous_calibration_from_same_source(client, db_session, tenant):
    customer, site, cam, sid, headers = await _session(client, db_session, tenant)
    cal_id = (await _calibrate(client, headers, sid)).json()["calibration"]["id"]
    sid2 = (await _create(client, headers, site, cam))["id"]
    r = await client.post(f"/api/v1/sessions/{sid2}/calibration", json={"reuse_calibration_id": cal_id},
                          headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["calibration"]["id"] == cal_id and r.json()["session"]["calibration_id"] == cal_id
    listed = await client.get(f"/api/v1/cameras/{cam.id}/calibrations", headers=headers)
    assert listed.status_code == 200 and [c["id"] for c in listed.json()["items"]] == [cal_id]

    other_site, other_source = await _site_with_camera(db_session, customer)
    sid3 = (await _create(client, headers, other_site, other_source))["id"]
    r = await client.post(f"/api/v1/sessions/{sid3}/calibration", json={"reuse_calibration_id": cal_id},
                          headers=headers)
    assert r.status_code == 404
    r = await client.post(f"/api/v1/sessions/{sid2}/calibration",
                          json={"reuse_calibration_id": str(uuid.uuid4())}, headers=headers)
    assert r.status_code == 404


async def test_calibrations_list_newest_first_and_scoped(client, db_session, tenant):
    _, _, cam, sid, headers = await _session(client, db_session, tenant)
    first = (await _calibrate(client, headers, sid)).json()["calibration"]["id"]
    second = (await _calibrate(client, headers, sid)).json()["calibration"]["id"]
    older = await db_session.get(Calibration, uuid.UUID(first))
    older.created_at = older.created_at - timedelta(hours=1)  # one transaction => identical now()
    await db_session.flush()
    listed = await client.get(f"/api/v1/cameras/{cam.id}/calibrations", headers=headers)
    assert [c["id"] for c in listed.json()["items"]] == [second, first]
    _, _, other = await tenant("customer_admin")
    assert (await client.get(f"/api/v1/cameras/{cam.id}/calibrations", headers=other)).status_code == 404


async def test_calibration_on_ready_session_enqueues_metrics(client, db_session, tenant, sessions_queue):
    _, _, _, sid, headers = await _session(client, db_session, tenant)
    assert (await _calibrate(client, headers, sid)).status_code == 201
    assert sessions_queue.jobs == []  # not ready yet: nothing to recompute
    s = await db_session.get(Session, uuid.UUID(sid))
    s.status = "ready"
    await db_session.flush()
    assert (await _calibrate(client, headers, sid)).status_code == 201
    assert [j.func_name for j in sessions_queue.jobs] == ["app.worker.session_jobs.compute_session_metrics"]
    assert sessions_queue.jobs[0].args == (sid,)


async def test_viewer_cannot_calibrate(client, db_session, tenant, make_user, auth_headers):
    customer, _, _, sid, _ = await _session(client, db_session, tenant)
    viewer = auth_headers(await make_user(customer, "viewer"))
    assert (await _calibrate(client, viewer, sid)).status_code == 403


async def test_other_customers_session_calibration_is_404(client, db_session, tenant):
    _, _, _, sid, _ = await _session(client, db_session, tenant)
    _, _, other = await tenant("operator")
    assert (await _calibrate(client, other, sid)).status_code == 404


async def _uploaded(client, db_session, tenant, tmp_path):
    customer, site, cam, sid, headers = await _session(client, db_session, tenant)
    clip = make_clip(tmp_path / "c.mp4", seconds=2).read_bytes()
    assert (await tus_upload(client, headers, sid, clip)).status_code == 204
    video = (await db_session.execute(select(SessionVideo).where(SessionVideo.session_id == uuid.UUID(sid)))).scalar_one()
    return sid, video, headers, customer


async def test_frame_endpoint_returns_signed_jpeg_url(client, db_session, tenant, tmp_path, media_storage):
    sid, video, headers, _ = await _uploaded(client, db_session, tenant, tmp_path)
    r = await client.get(f"/api/v1/sessions/{sid}/videos/{video.id}/frame?t_ms=500", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["width"], data["height"]) == (640, 360)
    key = f"sessions/{video.customer_id}/{sid}/analysis/frame_{video.id}_500.jpg"
    assert key in data["url"] and media_storage.exists(key)
    img = await client.get(data["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert img.content[:2] == b"\xff\xd8"


async def test_frame_is_cached(client, db_session, tenant, tmp_path, media_storage, monkeypatch):
    sid, video, headers, _ = await _uploaded(client, db_session, tenant, tmp_path)
    url = f"/api/v1/sessions/{sid}/videos/{video.id}/frame?t_ms=0"
    assert (await client.get(url, headers=headers)).status_code == 200
    import app.sessions.calibration as mod

    def boom(*a, **k):
        raise AssertionError("re-extracted")
    monkeypatch.setattr(mod, "extract_frame", boom)
    assert (await client.get(url, headers=headers)).status_code == 200


async def test_frame_beyond_duration_is_422_and_unfinished_video_is_409(client, db_session, tenant, tmp_path):
    sid, video, headers, _ = await _uploaded(client, db_session, tenant, tmp_path)
    r = await client.get(f"/api/v1/sessions/{sid}/videos/{video.id}/frame?t_ms=999999", headers=headers)
    assert r.status_code == 422 and r.json()["type"].endswith("/validation")
    assert (await client.get(f"/api/v1/sessions/{sid}/videos/{uuid.uuid4()}/frame", headers=headers)).status_code == 404
    video.status = "uploading"
    await db_session.flush()
    r = await client.get(f"/api/v1/sessions/{sid}/videos/{video.id}/frame", headers=headers)
    assert r.status_code == 409


async def test_viewer_can_get_frame(client, db_session, tenant, tmp_path, make_user, auth_headers):
    sid, video, _, customer = await _uploaded(client, db_session, tenant, tmp_path)
    viewer = auth_headers(await make_user(customer, "viewer"))
    r = await client.get(f"/api/v1/sessions/{sid}/videos/{video.id}/frame", headers=viewer)
    assert r.status_code == 200


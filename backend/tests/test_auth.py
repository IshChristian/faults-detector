from fastapi import Depends
from sqlalchemy import select

from app.auth.deps import require_roles
from app.models import RefreshToken

PW = "Passw0rd!long"


async def _login(client, email, password=PW):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_login_success_returns_tokens_and_httponly_cookie(client, make_customer, make_user):
    c = await make_customer(industry="sports")
    u = await make_user(c, "operator", email="coach@academy.rw")
    r = await _login(client, "coach@academy.rw")
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["refresh_token"] and body["token_type"] == "bearer"
    assert body["user"] == {"id": str(u.id), "email": "coach@academy.rw", "full_name": u.full_name,
                            "role": "operator", "customer_id": str(c.id), "customer_industry": "sports"}
    cookie = r.headers["set-cookie"].lower()
    assert "vg_refresh=" in cookie and "httponly" in cookie
    assert "samesite=strict" in cookie and "path=/api/v1/auth" in cookie


async def test_login_email_is_case_insensitive(client, make_customer, make_user):
    c = await make_customer()
    await make_user(c, "operator", email="coach@academy.rw")
    assert (await _login(client, "Coach@Academy.rw")).status_code == 200


async def test_login_wrong_password_and_inactive_are_identical_401(client, make_customer, make_user):
    c = await make_customer()
    await make_user(c, "operator", email="a@x.rw")
    await make_user(c, "operator", email="b@x.rw", is_active=False)
    wrong = await _login(client, "a@x.rw", "nope-nope-nope")
    inactive = await _login(client, "b@x.rw")
    unknown = await _login(client, "nobody@x.rw")
    for r in (wrong, inactive, unknown):
        assert r.status_code == 401
        assert r.json() == wrong.json()
    assert wrong.json()["type"].endswith("/invalid-credentials")


async def test_login_rate_limited_on_sixth_attempt_within_a_minute(client, make_customer, make_user):
    c = await make_customer()
    await make_user(c, "operator", email="a@x.rw")
    statuses = [(await _login(client, "a@x.rw", "wrong-password")).status_code for _ in range(6)]
    assert statuses == [401] * 5 + [429]
    r = await _login(client, "a@x.rw")  # even the right password is refused while limited
    assert r.status_code == 429 and r.json()["type"].endswith("/rate-limited")


async def test_refresh_rotates_token(client, db_session, make_customer, make_user):
    c = await make_customer()
    await make_user(c, "operator", email="a@x.rw")
    old = (await _login(client, "a@x.rw")).json()["refresh_token"]
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 200
    new = r.json()["refresh_token"]
    assert new != old and r.json()["access_token"]
    rows = (await db_session.execute(select(RefreshToken))).scalars().all()
    assert sum(1 for t in rows if t.revoked_at is None) == 1


async def test_refresh_via_cookie(client, make_customer, make_user):
    c = await make_customer()
    await make_user(c, "operator", email="a@x.rw")
    await _login(client, "a@x.rw")  # sets the vg_refresh cookie in the client jar
    r = await client.post("/api/v1/auth/refresh")
    assert r.status_code == 200
    assert "vg_refresh=" in r.headers["set-cookie"]


async def test_refresh_reuse_revokes_all_user_tokens(client, make_customer, make_user):
    c = await make_customer()
    await make_user(c, "operator", email="a@x.rw")
    a = (await _login(client, "a@x.rw")).json()["refresh_token"]
    client.cookies.clear()
    b = (await client.post("/api/v1/auth/refresh", json={"refresh_token": a})).json()["refresh_token"]
    client.cookies.clear()
    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": a})
    assert reuse.status_code == 401
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": b})).status_code == 401


async def test_logout_revokes_refresh(client, make_customer, make_user):
    c = await make_customer()
    await make_user(c, "operator", email="a@x.rw")
    token = (await _login(client, "a@x.rw")).json()["refresh_token"]
    r = await client.post("/api/v1/auth/logout", json={"refresh_token": token})
    assert r.status_code == 204
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": token})).status_code == 401


async def test_me_requires_valid_access_token(client, make_customer, make_user, auth_headers):
    c = await make_customer()
    u = await make_user(c, "viewer")
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"})).status_code == 401
    r = await client.get("/api/v1/auth/me", headers=auth_headers(u))
    assert r.status_code == 200 and r.json()["role"] == "viewer"


async def test_deactivated_user_access_token_stops_working(client, db_session, make_customer, make_user, auth_headers):
    c = await make_customer()
    u = await make_user(c, "viewer")
    headers = auth_headers(u)
    u.is_active = False
    await db_session.flush()
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_require_roles_blocks_viewer(client, make_customer, make_user, auth_headers):
    app = client._transport.app

    @app.get("/api/v1/_test/admin-only")
    async def admin_only(_=Depends(require_roles("customer_admin"))):
        return {"ok": True}

    c = await make_customer()
    viewer = await make_user(c, "viewer")
    admin = await make_user(c, "customer_admin")
    superadmin = await make_user(None, "super_admin")
    assert (await client.get("/api/v1/_test/admin-only", headers=auth_headers(viewer))).status_code == 403
    assert (await client.get("/api/v1/_test/admin-only", headers=auth_headers(admin))).status_code == 200
    assert (await client.get("/api/v1/_test/admin-only", headers=auth_headers(superadmin))).status_code == 200

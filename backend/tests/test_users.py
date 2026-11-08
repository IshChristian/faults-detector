from sqlalchemy import select

from app.models import AuditLog

NEW = {"email": "coach@academy.rw", "full_name": "Coach One", "password": "long-enough-pw", "role": "operator"}


async def test_customer_admin_creates_user_who_can_log_in(client, tenant):
    c, _, h = await tenant()
    r = await client.post("/api/v1/users", json=NEW, headers=h)
    assert r.status_code == 201
    assert r.json()["customer_id"] == str(c.id) and r.json()["role"] == "operator"
    login = await client.post("/api/v1/auth/login", json={"email": NEW["email"], "password": NEW["password"]})
    assert login.status_code == 200


async def test_duplicate_email_case_insensitive_is_409(client, tenant):
    _, _, h = await tenant()
    assert (await client.post("/api/v1/users", json=NEW, headers=h)).status_code == 201
    r = await client.post("/api/v1/users", json={**NEW, "email": "Coach@Academy.RW"}, headers=h)
    assert r.status_code == 409


async def test_cannot_create_super_admin_via_api(client, tenant):
    _, _, h = await tenant()
    assert (await client.post("/api/v1/users", json={**NEW, "role": "super_admin"}, headers=h)).status_code == 422


async def test_short_password_is_422(client, tenant):
    _, _, h = await tenant()
    assert (await client.post("/api/v1/users", json={**NEW, "password": "short"}, headers=h)).status_code == 422


async def test_only_customer_admin_manages_users(client, tenant, make_user, auth_headers):
    c, _, _ = await tenant()
    op = auth_headers(await make_user(c, "operator"))
    assert (await client.get("/api/v1/users", headers=op)).status_code == 403
    assert (await client.post("/api/v1/users", json=NEW, headers=op)).status_code == 403


async def test_delete_deactivates_and_revokes_tokens(client, db_session, tenant):
    _, _, h = await tenant()
    uid = (await client.post("/api/v1/users", json=NEW, headers=h)).json()["id"]
    refresh = (await client.post("/api/v1/auth/login", json={"email": NEW["email"], "password": NEW["password"]})).json()["refresh_token"]
    client.cookies.clear()
    assert (await client.delete(f"/api/v1/users/{uid}", headers=h)).status_code == 204
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})).status_code == 401
    login = await client.post("/api/v1/auth/login", json={"email": NEW["email"], "password": NEW["password"]})
    assert login.status_code == 401
    assert (await client.get(f"/api/v1/users/{uid}", headers=h)).json()["is_active"] is False


async def test_cannot_deactivate_self(client, tenant):
    _, u, h = await tenant()
    assert (await client.delete(f"/api/v1/users/{u.id}", headers=h)).status_code == 409


async def test_password_hash_never_returned(client, tenant):
    _, _, h = await tenant()
    created = await client.post("/api/v1/users", json=NEW, headers=h)
    listing = await client.get("/api/v1/users", headers=h)
    one = await client.get(f"/api/v1/users/{created.json()['id']}", headers=h)
    for r in (created, listing, one):
        assert "password" not in r.text


async def test_patch_user_role_and_password(client, tenant):
    _, _, h = await tenant()
    uid = (await client.post("/api/v1/users", json=NEW, headers=h)).json()["id"]
    r = await client.patch(f"/api/v1/users/{uid}", json={"role": "viewer", "password": "brand-new-password"}, headers=h)
    assert r.status_code == 200 and r.json()["role"] == "viewer"
    login = await client.post("/api/v1/auth/login", json={"email": NEW["email"], "password": "brand-new-password"})
    assert login.status_code == 200


async def test_other_customers_user_is_404_and_not_listed(client, tenant):
    _, _, h_a = await tenant()
    _, _, h_b = await tenant()
    uid = (await client.post("/api/v1/users", json=NEW, headers=h_b)).json()["id"]
    url = f"/api/v1/users/{uid}"
    assert (await client.get(url, headers=h_a)).status_code == 404
    assert (await client.patch(url, json={"full_name": "x"}, headers=h_a)).status_code == 404
    assert (await client.delete(url, headers=h_a)).status_code == 404
    assert uid not in (await client.get("/api/v1/users", headers=h_a)).text


async def test_user_create_is_audited_without_password(client, db_session, tenant):
    c, _, h = await tenant()
    await client.post("/api/v1/users", json=NEW, headers=h)
    row = (await db_session.execute(select(AuditLog).where(
        AuditLog.action == "user.create", AuditLog.customer_id == c.id))).scalar_one()
    assert NEW["password"] not in str(row.details)

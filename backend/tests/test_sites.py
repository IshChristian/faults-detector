from sqlalchemy import select

from app.models import AuditLog, Site


async def test_customer_admin_creates_and_lists_site(client, tenant):
    c, _, h = await tenant()
    r = await client.post("/api/v1/sites", json={"name": "Main pitch", "location": "Kigali"}, headers=h)
    assert r.status_code == 201
    site = r.json()
    assert site["name"] == "Main pitch" and site["timezone"] == "Africa/Kigali"
    assert site["customer_id"] == str(c.id)
    listing = (await client.get("/api/v1/sites", headers=h)).json()
    assert [s["id"] for s in listing["items"]] == [site["id"]] and listing["next_cursor"] is None


async def test_operator_and_viewer_cannot_create_site_but_can_read(client, tenant, make_user, auth_headers):
    c, _, admin_h = await tenant()
    site = (await client.post("/api/v1/sites", json={"name": "A"}, headers=admin_h)).json()
    for role in ("operator", "viewer"):
        h = auth_headers(await make_user(c, role))
        assert (await client.post("/api/v1/sites", json={"name": "B"}, headers=h)).status_code == 403
        assert (await client.get(f"/api/v1/sites/{site['id']}", headers=h)).status_code == 200


async def test_other_customers_site_is_404_for_get_patch_delete(client, tenant):
    _, _, h_a = await tenant()
    _, _, h_b = await tenant()
    site = (await client.post("/api/v1/sites", json={"name": "B site"}, headers=h_b)).json()
    url = f"/api/v1/sites/{site['id']}"
    assert (await client.get(url, headers=h_a)).status_code == 404
    assert (await client.patch(url, json={"name": "hijack"}, headers=h_a)).status_code == 404
    assert (await client.delete(url, headers=h_a)).status_code == 404
    assert (await client.get(url, headers=h_b)).json()["name"] == "B site"


async def test_list_never_includes_other_customers_sites(client, tenant):
    _, _, h_a = await tenant()
    _, _, h_b = await tenant()
    await client.post("/api/v1/sites", json={"name": "B site"}, headers=h_b)
    assert (await client.get("/api/v1/sites", headers=h_a)).json()["items"] == []


async def test_super_admin_create_site_requires_customer_id(client, make_customer, make_user, auth_headers):
    h = auth_headers(await make_user(None, "super_admin"))
    r = await client.post("/api/v1/sites", json={"name": "X"}, headers=h)
    assert r.status_code == 422 and r.json()["detail"] == "customer_id is required"
    c = await make_customer()
    r = await client.post("/api/v1/sites", json={"name": "X", "customer_id": str(c.id)}, headers=h)
    assert r.status_code == 201 and r.json()["customer_id"] == str(c.id)


async def test_customer_admin_customer_id_in_body_is_ignored(client, tenant, make_customer):
    c, _, h = await tenant()
    other = await make_customer()
    r = await client.post("/api/v1/sites", json={"name": "X", "customer_id": str(other.id)}, headers=h)
    assert r.status_code == 201 and r.json()["customer_id"] == str(c.id)


async def test_invalid_timezone_is_422(client, tenant):
    _, _, h = await tenant()
    r = await client.post("/api/v1/sites", json={"name": "X", "timezone": "Mars/Olympus"}, headers=h)
    assert r.status_code == 422
    r = await client.post("/api/v1/sites", json={"name": "X"}, headers=h)
    r = await client.patch(f"/api/v1/sites/{r.json()['id']}", json={"timezone": "Nope/Nope"}, headers=h)
    assert r.status_code == 422


async def test_patch_and_delete_site(client, db_session, tenant):
    _, _, h = await tenant()
    site = (await client.post("/api/v1/sites", json={"name": "Old"}, headers=h)).json()
    url = f"/api/v1/sites/{site['id']}"
    r = await client.patch(url, json={"name": "New", "timezone": "Europe/London"}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "New" and r.json()["timezone"] == "Europe/London"
    assert (await client.delete(url, headers=h)).status_code == 204
    assert (await client.get(url, headers=h)).status_code == 404


async def test_site_create_is_audited(client, db_session, tenant):
    c, u, h = await tenant()
    site = (await client.post("/api/v1/sites", json={"name": "A"}, headers=h)).json()
    row = (await db_session.execute(select(AuditLog).where(AuditLog.action == "site.create"))).scalar_one()
    assert row.actor_user_id == u.id and row.customer_id == c.id
    assert str(row.entity_id) == site["id"] and row.entity_type == "site"

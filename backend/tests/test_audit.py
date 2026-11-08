import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.audit.service import record_audit
from app.auth.deps import CurrentUser
from app.models import AuditLog, User


async def _rows(db_session, action):
    return (await db_session.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all()


async def test_login_writes_audit_row(client, db_session, make_customer, make_user):
    c = await make_customer()
    u = await make_user(c, "operator", email="a@x.rw")
    assert (await client.post("/api/v1/auth/login", json={"email": "a@x.rw", "password": "Passw0rd!long"})).status_code == 200
    [row] = await _rows(db_session, "auth.login")
    assert row.actor_user_id == u.id and row.customer_id == c.id
    assert str(row.ip_address) == "127.0.0.1"


async def test_failed_login_writes_audit_without_actor(client, db_session, make_customer, make_user):
    c = await make_customer()
    await make_user(c, "operator", email="a@x.rw")
    r = await client.post("/api/v1/auth/login", json={"email": "A@x.rw", "password": "wrong-password"})
    assert r.status_code == 401
    [row] = await _rows(db_session, "auth.login_failed")
    assert row.actor_user_id is None
    assert row.details == {"email": "a@x.rw"}


async def test_logout_writes_audit_row(client, db_session, make_customer, make_user):
    c = await make_customer()
    u = await make_user(c, "operator", email="a@x.rw")
    token = (await client.post("/api/v1/auth/login", json={"email": "a@x.rw", "password": "Passw0rd!long"})).json()["refresh_token"]
    assert (await client.post("/api/v1/auth/logout", json={"refresh_token": token})).status_code == 204
    [row] = await _rows(db_session, "auth.logout")
    assert row.actor_user_id == u.id


async def test_audit_rows_cannot_be_updated(db_session, make_customer):
    c = await make_customer()
    await record_audit(db_session, action="site.create", customer_id=c.id, details={"name": "A"})
    await db_session.flush()
    for stmt in ("update audit_logs set action='tampered'", "update audit_logs set details='{}'"):
        with pytest.raises(DBAPIError, match="append-only"):
            async with db_session.begin_nested():
                await db_session.execute(text(stmt))


async def test_deleting_user_keeps_audit_row_with_null_actor(db_session, make_customer, make_user):
    c = await make_customer()
    u = await make_user(c, "operator")
    actor = CurrentUser(id=u.id, customer_id=c.id, role=u.role, email=u.email)
    await record_audit(db_session, action="event.review", customer_id=c.id, actor=actor, details={"k": 1})
    await db_session.flush()
    customer_id, user_id = c.id, u.id
    await db_session.execute(delete(User).where(User.id == user_id))
    db_session.expire_all()
    [row] = await _rows(db_session, "event.review")
    assert row.actor_user_id is None
    assert row.customer_id == customer_id and row.details == {"k": 1}

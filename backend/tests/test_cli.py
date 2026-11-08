import pytest
from sqlalchemy import func, select

from app.cli import DuplicateEmailError, create_customer_with_admin, create_super_admin, read_password
from app.models import AuditLog, Customer, User

PW = "a-strong-password"


async def test_create_customer_with_admin_then_admin_can_login(client, db_session):
    customer, admin = await create_customer_with_admin(
        db_session, "Kigali Academy", "sports", "Admin@Academy.rw", "Head Coach", PW)
    assert customer.industry == "sports"
    assert admin.role == "customer_admin" and admin.customer_id == customer.id
    assert admin.email == "admin@academy.rw"
    r = await client.post("/api/v1/auth/login", json={"email": "admin@academy.rw", "password": PW})
    assert r.status_code == 200 and r.json()["user"]["customer_industry"] == "sports"
    actions = set((await db_session.execute(select(AuditLog.action))).scalars())
    assert "cli.create_customer" in actions


async def test_duplicate_admin_email_raises_without_side_effects(db_session):
    await create_customer_with_admin(db_session, "First", "sports", "a@x.rw", "A", PW)
    before = (await db_session.execute(select(func.count()).select_from(Customer))).scalar()
    with pytest.raises(DuplicateEmailError):
        await create_customer_with_admin(db_session, "Second", "retail", "A@X.rw", "B", PW)
    after = (await db_session.execute(select(func.count()).select_from(Customer))).scalar()
    assert before == after


async def test_super_admin_has_null_customer(db_session):
    user = await create_super_admin(db_session, "root@visionguard.rw", "Owner", PW)
    assert user.role == "super_admin" and user.customer_id is None
    with pytest.raises(DuplicateEmailError):
        await create_super_admin(db_session, "ROOT@visionguard.rw", "Owner 2", PW)
    count = (await db_session.execute(select(func.count()).select_from(User).where(User.role == "super_admin"))).scalar()
    assert count >= 1


def test_read_password_from_env_and_length_rule(monkeypatch):
    monkeypatch.setenv("VG_PASSWORD", PW)
    assert read_password() == PW
    monkeypatch.setenv("VG_PASSWORD", "short")
    with pytest.raises(SystemExit):
        read_password()


def test_read_password_prompts_twice_and_must_match(monkeypatch):
    monkeypatch.delenv("VG_PASSWORD", raising=False)
    answers = iter([PW, PW + "x"])
    monkeypatch.setattr("app.cli.getpass", lambda prompt="": next(answers))
    with pytest.raises(SystemExit):
        read_password()
    answers = iter([PW, PW])
    monkeypatch.setattr("app.cli.getpass", lambda prompt="": next(answers))
    assert read_password() == PW

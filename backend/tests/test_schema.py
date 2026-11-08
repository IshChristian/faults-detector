import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import Camera, Site


async def test_baseline_tables_exist(db_session):
    names = set((await db_session.execute(text(
        "select table_name from information_schema.tables where table_schema='public'"))).scalars())
    assert {"customers", "users", "sites", "cameras", "events", "rules", "models",
            "model_assignments", "audit_logs", "alembic_version"} <= names


async def test_camera_mode_defaults_to_live_and_is_constrained(db_session, make_customer):
    c = await make_customer()
    site = Site(customer_id=c.id, name="Pitch A"); db_session.add(site); await db_session.flush()
    cam = Camera(customer_id=c.id, site_id=site.id, name="Cam", source_type="rtsp", frigate_name="cam")
    db_session.add(cam); await db_session.flush(); await db_session.refresh(cam)
    assert cam.mode == "live"
    with pytest.raises(IntegrityError):
        await db_session.execute(text(f"update cameras set mode='bogus' where id='{cam.id}'"))


async def test_live_camera_without_frigate_name_is_rejected(db_session, make_customer):
    c = await make_customer()
    site = Site(customer_id=c.id, name="Pitch B"); db_session.add(site); await db_session.flush()
    db_session.add(Camera(customer_id=c.id, site_id=site.id, name="NoFrigate", source_type="rtsp"))
    with pytest.raises(IntegrityError):
        await db_session.flush()

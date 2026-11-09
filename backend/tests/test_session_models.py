from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import Camera, Session as TrainingSession, SessionTrack, SessionVideo, Site


@pytest.fixture
async def setup(db_session, make_customer):
    customer = await make_customer()
    site = Site(customer_id=customer.id, name="Pitch A")
    db_session.add(site)
    await db_session.flush()
    camera = Camera(customer_id=customer.id, site_id=site.id, name="Upload", mode="upload", source_type="file")
    db_session.add(camera)
    await db_session.flush()
    return customer, site, camera


async def _make_session(db_session, customer, site, camera) -> TrainingSession:
    s = TrainingSession(customer_id=customer.id, site_id=site.id, source_id=camera.id, type="training",
                        starts_at=datetime(2026, 11, 9, 10, 0, tzinfo=UTC))
    db_session.add(s)
    await db_session.flush()
    await db_session.refresh(s)
    return s


def _video(s, position: int) -> SessionVideo:
    return SessionVideo(customer_id=s.customer_id, session_id=s.id, position=position, size_bytes=10,
                        original_key=f"k/{position}.mp4")


async def test_session_defaults(db_session, setup):
    s = await _make_session(db_session, *setup)
    assert s.status == "uploading"
    assert s.progress == 0
    assert float(s.sprint_threshold_kmh) == 19.0
    assert s.sync_offset_ms == 0


async def test_session_status_is_constrained(db_session, setup):
    s = await _make_session(db_session, *setup)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(text("UPDATE sessions SET status = 'done' WHERE id = :id"), {"id": s.id})


async def test_video_positions_can_swap_in_one_transaction(db_session, setup):
    s = await _make_session(db_session, *setup)
    a, b = _video(s, 0), _video(s, 1)
    db_session.add_all([a, b])
    await db_session.flush()
    async with db_session.begin_nested():
        a.position, b.position = 1, 0
        await db_session.flush()
    rows = (await db_session.execute(
        select(SessionVideo.original_key).where(SessionVideo.session_id == s.id).order_by(SessionVideo.position)
    )).scalars().all()
    assert rows == ["k/1.mp4", "k/0.mp4"]


async def test_session_tracks_unique_per_session(db_session, setup):
    s = await _make_session(db_session, *setup)

    def track() -> SessionTrack:
        return SessionTrack(customer_id=s.customer_id, session_id=s.id, track_id=7, cls="person",
                            frames_count=5, first_ms=0, last_ms=100)

    db_session.add(track())
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(track())
            await db_session.flush()


async def test_deleting_session_cascades_videos_and_tracks(db_session, setup):
    s = await _make_session(db_session, *setup)
    db_session.add_all([_video(s, 0), SessionTrack(customer_id=s.customer_id, session_id=s.id, track_id=1,
                                                   cls="ball", frames_count=1, first_ms=0, last_ms=1)])
    await db_session.flush()
    await db_session.execute(text("DELETE FROM sessions WHERE id = :id"), {"id": s.id})
    for table in ("session_videos", "session_tracks"):
        count = (await db_session.execute(text(f"SELECT count(*) FROM {table} WHERE session_id = :id"),
                                          {"id": s.id})).scalar_one()
        assert count == 0

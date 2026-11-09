import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import ApiError
from app.models import Session, SessionVideo
from app.sessions.schemas import SessionDetail, SessionOut, VideoOut

UPLOADABLE = ("uploading", "ready", "failed")


def session_prefix(s: Session) -> str:
    return f"sessions/{s.customer_id}/{s.id}"


async def list_videos(db: AsyncSession, session_id: uuid.UUID) -> list[SessionVideo]:
    stmt = select(SessionVideo).where(SessionVideo.session_id == session_id).order_by(SessionVideo.position)
    return list((await db.execute(stmt)).scalars())


async def session_detail(db: AsyncSession, s: Session) -> SessionDetail:
    await db.refresh(s)
    videos = await list_videos(db, s.id)
    return SessionDetail(**SessionOut.model_validate(s).model_dump(),
                         videos=[VideoOut.model_validate(v) for v in videos])


async def reorder_by_creation_time(db: AsyncSession, session_id: uuid.UUID) -> None:
    """Timed videos first (by creation_time), then untimed ones by upload order; positions from 0."""
    videos = await list_videos(db, session_id)
    timed = sorted((v for v in videos if v.creation_time is not None), key=lambda v: v.creation_time)
    untimed = sorted((v for v in videos if v.creation_time is None), key=lambda v: v.created_at)
    for position, video in enumerate(timed + untimed):
        video.position = position
    await db.flush()  # (session_id, position) is deferrable, so renumbering in any order is safe


def ensure_processable(s: Session, videos: list[SessionVideo]) -> None:
    if s.status not in UPLOADABLE:
        raise ApiError(422, "not-processable", "Session cannot be processed",
                       detail=f"A session that is {s.status} cannot be processed")
    if not videos:
        raise ApiError(422, "not-processable", "Session cannot be processed", detail="Upload at least one video first")
    if any(v.status not in ("uploaded", "processed") for v in videos):
        raise ApiError(422, "not-processable", "Session cannot be processed",
                       detail="Every video must finish uploading (remove failed or unfinished ones) first")

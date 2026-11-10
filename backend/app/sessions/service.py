import uuid

import redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import ApiError
from app.models import Session, SessionVideo
from app.sessions.schemas import SessionDetail, SessionOut, VideoOut

UPLOADABLE = ("uploading", "ready", "failed")
STOPPED_UNEXPECTEDLY = "Processing stopped unexpectedly. Start it again."
_DEAD_JOB = (JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED)
# A metrics recompute is queued in these states; the single sessions worker runs it after any pending processing.
METRICS_RECOMPUTE = ("queued", "processing", "ready")


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


def enqueue_metrics(queue: Queue, s: Session) -> None:
    """Queue a metrics recompute; the caller commits first so the worker sees the change."""
    queue.enqueue("app.worker.session_jobs.compute_session_metrics", str(s.id), job_timeout=2 * 3600,
                  result_ttl=86400)


async def reconcile_stale_job(db: AsyncSession, s: Session, queue: Queue) -> None:
    """Mark a queued or processing session failed when its RQ job is gone or dead (timeout, OOM kill, restart).

    A session without a job id is left alone: there is nothing to check it against. If Valkey can't be reached
    the session is left as it is rather than failing the request.
    """
    if s.status not in ("queued", "processing") or s.job_id is None:
        return
    try:
        status = Job.fetch(s.job_id, connection=queue.connection).get_status(refresh=False)
    except NoSuchJobError:
        status = None
    except redis.RedisError:
        return
    if status is None or status in _DEAD_JOB:
        s.status, s.error = "failed", STOPPED_UNEXPECTEDLY
        await db.flush()


def invalidate_results(s: Session) -> None:
    """The video set or order changed: a ready or failed session's results no longer match its videos.

    Back to 'uploading' so it must be processed again; videos keep their own status."""
    if s.status in ("ready", "failed"):
        s.status, s.summary_key, s.error = "uploading", None, None


def ensure_processable(s: Session, videos: list[SessionVideo]) -> None:
    if s.status not in UPLOADABLE:
        raise ApiError(422, "not-processable", "Session cannot be processed",
                       detail=f"A session that is {s.status} cannot be processed")
    if not videos:
        raise ApiError(422, "not-processable", "Session cannot be processed", detail="Upload at least one video first")
    if any(v.status not in ("uploaded", "processed") for v in videos):
        raise ApiError(422, "not-processable", "Session cannot be processed",
                       detail="Every video must finish uploading (remove failed or unfinished ones) first")

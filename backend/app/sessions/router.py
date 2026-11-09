import uuid

from fastapi import APIRouter, Depends, Query, Request
from rq import Queue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.deps import CurrentUser, get_current_user, require_roles
from app.common.errors import ApiError
from app.common.pagination import Page, limit_param, paginate
from app.common.request import client_ip
from app.db import get_session
from app.models import Camera, Session, Site
from app.sessions import service
from app.sessions.schemas import SessionCreate, SessionDetail, SessionOut, SessionStatus, SessionUpdate, VideoOrder
from app.tenancy.scoping import get_scoped_or_404, scoped
from app.worker.queues import get_sessions_queue

router = APIRouter(prefix="/sessions", tags=["sessions"])
writer = require_roles("customer_admin", "operator")


@router.post("", response_model=SessionDetail, status_code=201)
async def create_session(body: SessionCreate, request: Request, user: CurrentUser = Depends(writer),
                         db: AsyncSession = Depends(get_session)):
    site = await get_scoped_or_404(db, Site, body.site_id, user, "site")
    source = (await db.execute(select(Camera).where(
        Camera.id == body.source_id, Camera.site_id == site.id, Camera.mode == "upload"))).scalar_one_or_none()
    if source is None:
        raise ApiError(422, "validation", "Validation failed",
                       errors=[{"field": "source_id", "message": "must be an upload camera of this site"}])
    values = body.model_dump(exclude_none=True)
    s = Session(customer_id=site.customer_id, created_by=user.id, **values)
    db.add(s)
    await db.flush()
    await record_audit(db, action="session.create", customer_id=s.customer_id, actor=user, entity_type="session",
                       entity_id=s.id, details={"site_id": str(site.id), "type": s.type}, ip=client_ip(request))
    return await service.session_detail(db, s)


@router.get("", response_model=Page[SessionOut])
async def list_sessions(site_id: uuid.UUID | None = None, status: SessionStatus | None = None,
                        limit: int = Depends(limit_param), cursor: str | None = Query(None),
                        user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    stmt = scoped(select(Session), Session, user)
    if site_id:
        stmt = stmt.where(Session.site_id == site_id)
    if status:
        stmt = stmt.where(Session.status == status)
    items, next_cursor = await paginate(db, stmt, Session, limit, cursor)
    return Page[SessionOut](items=[SessionOut.model_validate(s) for s in items], next_cursor=next_cursor)


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session_detail(session_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                             db: AsyncSession = Depends(get_session)):
    return await service.session_detail(db, await get_scoped_or_404(db, Session, session_id, user, "session"))


@router.patch("/{session_id}", response_model=SessionDetail)
async def update_session(session_id: uuid.UUID, body: SessionUpdate, request: Request,
                         user: CurrentUser = Depends(writer), db: AsyncSession = Depends(get_session),
                         queue: Queue = Depends(get_sessions_queue)):
    s = await get_scoped_or_404(db, Session, session_id, user, "session")
    changes = body.model_dump(exclude_unset=True)
    threshold_changed = "sprint_threshold_kmh" in changes and float(s.sprint_threshold_kmh) != changes[
        "sprint_threshold_kmh"]
    for field, value in changes.items():
        setattr(s, field, value)
    await db.flush()
    await record_audit(db, action="session.update", customer_id=s.customer_id, actor=user, entity_type="session",
                       entity_id=s.id, details={"fields": sorted(changes)}, ip=client_ip(request))
    detail = await service.session_detail(db, s)
    if threshold_changed and s.status == "ready" and s.calibration_id is not None:
        await db.commit()  # the worker must see the new threshold
        queue.enqueue("app.worker.session_jobs.compute_session_metrics", str(s.id))
    return detail


@router.put("/{session_id}/video-order", response_model=SessionDetail)
async def set_video_order(session_id: uuid.UUID, body: VideoOrder, user: CurrentUser = Depends(writer),
                          db: AsyncSession = Depends(get_session)):
    s = await get_scoped_or_404(db, Session, session_id, user, "session")
    videos = {v.id: v for v in await service.list_videos(db, s.id)}
    if len(body.video_ids) != len(videos) or set(body.video_ids) != set(videos):
        raise ApiError(422, "validation", "Validation failed",
                       errors=[{"field": "video_ids", "message": "must list each of the session's videos exactly once"}])
    for position, video_id in enumerate(body.video_ids):
        videos[video_id].position = position
    await db.flush()
    return await service.session_detail(db, s)


@router.post("/{session_id}/process", response_model=SessionDetail, status_code=202)
async def process_session(session_id: uuid.UUID, request: Request, user: CurrentUser = Depends(writer),
                          db: AsyncSession = Depends(get_session), queue: Queue = Depends(get_sessions_queue)):
    s = await get_scoped_or_404(db, Session, session_id, user, "session")
    service.ensure_processable(s, await service.list_videos(db, s.id))
    s.status, s.progress, s.stage, s.error = "queued", 0, None, None
    await db.flush()
    await record_audit(db, action="session.process", customer_id=s.customer_id, actor=user, entity_type="session",
                       entity_id=s.id, ip=client_ip(request))
    detail = await service.session_detail(db, s)
    await db.commit()  # the worker must see status=queued before it picks the job up
    queue.enqueue("app.worker.session_jobs.process_session", str(s.id), job_timeout=12 * 3600, result_ttl=86400)
    return detail

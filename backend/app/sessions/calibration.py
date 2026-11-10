import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from rq import Queue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.pitch import LANDMARKS, CalibrationError, fit_homography
from app.audit.service import record_audit
from app.auth.deps import CurrentUser, get_current_user, require_roles
from app.common.errors import ApiError, conflict, not_found
from app.common.pagination import Page, limit_param, paginate
from app.common.request import client_ip
from app.db import get_session
from app.models import Calibration, Camera, Session, SessionVideo
from app.sessions import service
from app.sessions.schemas import SessionDetail
from app.storage.base import Storage, get_storage
from app.storage.local import scratch_dir
from app.storage.signing import sign_media_url
from app.tenancy.scoping import get_scoped_or_404, scoped
from app.video.ffmpeg import VideoError, extract_frame
from app.worker.queues import get_sessions_queue

router = APIRouter(tags=["calibration"])
writer = require_roles("customer_admin", "operator")
FRAME_URL_TTL_S = 900

Pt = tuple[float, float]


class FrameOut(BaseModel):
    url: str
    width: int
    height: int


class CalibrationCreate(BaseModel):
    image_points: list[Pt] | None = None
    landmarks: list[str] | None = None
    pitch_points: list[Pt] | None = None
    pitch_length_m: float = Field(100, ge=10, le=200)
    pitch_width_m: float = Field(64, ge=10, le=200)
    reuse_calibration_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_mode(self):
        if self.reuse_calibration_id is not None:
            if any(v is not None for v in (self.image_points, self.landmarks, self.pitch_points)):
                raise ValueError("reuse_calibration_id cannot be combined with points")
            return self
        if self.image_points is None:
            raise ValueError("image_points or reuse_calibration_id is required")
        if (self.landmarks is None) == (self.pitch_points is None):
            raise ValueError("provide exactly one of landmarks or pitch_points")
        return self


class CalibrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    camera_id: uuid.UUID
    image_points: list
    pitch_points: list
    pitch_length_m: float
    pitch_width_m: float
    created_by: uuid.UUID | None
    created_at: str

    @classmethod
    def of(cls, c: Calibration) -> "CalibrationOut":
        return cls.model_validate({**{k: getattr(c, k) for k in cls.model_fields if k != "created_at"},
                                   "created_at": c.created_at.isoformat()})


class CalibrationSaved(BaseModel):
    calibration: CalibrationOut
    session: SessionDetail


def _validation(field: str, message: str) -> ApiError:
    return ApiError(422, "validation", "Validation failed", errors=[{"field": field, "message": message}])


@router.get("/sessions/{session_id}/videos/{video_id}/frame", response_model=FrameOut)
async def get_frame(session_id: uuid.UUID, video_id: uuid.UUID, t_ms: int = Query(0, ge=0),
                    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session),
                    storage: Storage = Depends(get_storage)):
    s = await get_scoped_or_404(db, Session, session_id, user, "session")
    video = (await db.execute(select(SessionVideo).where(
        SessionVideo.id == video_id, SessionVideo.session_id == s.id))).scalar_one_or_none()
    if video is None:
        raise not_found("video")
    if video.status not in ("uploaded", "processed"):
        raise conflict("The video has not finished uploading")
    if video.duration_ms is not None and t_ms > video.duration_ms:
        raise _validation("t_ms", "is beyond the end of the video")
    key = f"{service.session_prefix(s)}/analysis/frame_{video.id}_{t_ms}.jpg"
    if not storage.exists(key):
        src = storage.local_path(video.original_key)
        if src is None:
            raise not_found("video file")
        with scratch_dir() as tmp:
            dest = Path(tmp) / "frame.jpg"
            try:
                extract_frame(src, t_ms, dest)
            except VideoError as e:
                raise _validation("t_ms", "no frame could be read at this time") from e
            storage.import_file(key, dest)
    return FrameOut(url=sign_media_url(key, ttl_seconds=FRAME_URL_TTL_S), width=video.width or 0,
                    height=video.height or 0)


@router.post("/sessions/{session_id}/calibration", response_model=CalibrationSaved, status_code=201)
async def save_calibration(session_id: uuid.UUID, body: CalibrationCreate, request: Request,
                           user: CurrentUser = Depends(writer), db: AsyncSession = Depends(get_session),
                           queue: Queue = Depends(get_sessions_queue)):
    s = await get_scoped_or_404(db, Session, session_id, user, "session")
    if body.reuse_calibration_id is not None:
        cal = (await db.execute(scoped(select(Calibration).where(
            Calibration.id == body.reuse_calibration_id, Calibration.camera_id == s.source_id),
            Calibration, user))).scalar_one_or_none()
        if cal is None:
            raise not_found("calibration")
    else:
        if body.landmarks is not None:
            unknown = [n for n in body.landmarks if n not in LANDMARKS]
            if unknown:
                raise _validation("landmarks", f"unknown landmark: {', '.join(unknown)}")
            pitch_points = [LANDMARKS[n](body.pitch_length_m, body.pitch_width_m) for n in body.landmarks]
        else:
            pitch_points = body.pitch_points
        try:
            fit_homography(body.image_points, pitch_points)
        except CalibrationError as e:
            raise ApiError(422, "invalid-calibration", "Invalid calibration", detail=str(e)) from e
        cal = Calibration(customer_id=s.customer_id, camera_id=s.source_id,
                          image_points=[list(p) for p in body.image_points],
                          pitch_points=[list(p) for p in pitch_points], pitch_length_m=body.pitch_length_m,
                          pitch_width_m=body.pitch_width_m, created_by=user.id)
        db.add(cal)
        await db.flush()
        await db.refresh(cal)
    s.calibration_id = cal.id
    await db.flush()
    await record_audit(db, action="calibration.save", customer_id=s.customer_id, actor=user, entity_type="session",
                       entity_id=s.id, details={"calibration_id": str(cal.id), "reused": body.reuse_calibration_id
                                                is not None}, ip=client_ip(request))
    out = CalibrationSaved(calibration=CalibrationOut.of(cal), session=await service.session_detail(db, s))
    if s.status in service.METRICS_RECOMPUTE:
        await db.commit()  # the worker must see the new calibration
        service.enqueue_metrics(queue, s)
    return out


@router.get("/cameras/{camera_id}/calibrations", response_model=Page[CalibrationOut])
async def list_calibrations(camera_id: uuid.UUID, limit: int = Depends(limit_param), cursor: str | None = Query(None),
                            user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    cam = await get_scoped_or_404(db, Camera, camera_id, user, "camera")
    stmt = select(Calibration).where(Calibration.camera_id == cam.id)
    items, next_cursor = await paginate(db, stmt, Calibration, limit, cursor)
    return Page[CalibrationOut](items=[CalibrationOut.of(c) for c in items], next_cursor=next_cursor)

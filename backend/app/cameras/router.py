import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.deps import CurrentUser, get_current_user, require_roles
from app.cameras.schemas import CameraCreate, CameraOut, CameraUpdate, Mode
from app.common.db import flush_or_conflict
from app.common.errors import ApiError, forbidden
from app.common.pagination import Page, limit_param, paginate
from app.common.request import client_ip
from app.db import get_session
from app.models import Camera, Site
from app.security.crypto import encrypt_secret
from app.tenancy.scoping import get_scoped_or_404, scoped

router = APIRouter(prefix="/cameras", tags=["cameras"])
writer = require_roles("customer_admin")
creator = require_roles("customer_admin", "operator")  # operators may add upload positions only
DUPLICATE = "A camera with this name or Frigate name already exists on this site"


@router.get("", response_model=Page[CameraOut])
async def list_cameras(site_id: uuid.UUID | None = None, mode: Mode | None = None,
                       limit: int = Depends(limit_param), cursor: str | None = Query(None),
                       user: CurrentUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    stmt = scoped(select(Camera), Camera, user)
    if site_id:
        stmt = stmt.where(Camera.site_id == site_id)
    if mode:
        stmt = stmt.where(Camera.mode == mode)
    items, next_cursor = await paginate(session, stmt, Camera, limit, cursor)
    return Page[CameraOut](items=[CameraOut.from_camera(c) for c in items], next_cursor=next_cursor)


@router.post("", response_model=CameraOut, status_code=201)
async def create_camera(body: CameraCreate, request: Request, user: CurrentUser = Depends(creator),
                        session: AsyncSession = Depends(get_session)):
    site = await get_scoped_or_404(session, Site, body.site_id, user, "site")
    if user.role == "operator" and body.mode != "upload":
        raise forbidden()
    cam = Camera(customer_id=site.customer_id, site_id=site.id, name=body.name, mode=body.mode,
                 source_type=body.source_type, frigate_name=body.frigate_name, resolution=body.resolution,
                 fps=body.fps, source_url_encrypted=encrypt_secret(body.source_url) if body.source_url else None)
    session.add(cam)
    await flush_or_conflict(session, DUPLICATE)
    await session.refresh(cam)
    await record_audit(session, action="camera.create", customer_id=cam.customer_id, actor=user,
                       entity_type="camera", entity_id=cam.id, details={"name": cam.name, "mode": cam.mode},
                       ip=client_ip(request))
    return CameraOut.from_camera(cam)


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera(camera_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                     session: AsyncSession = Depends(get_session)):
    return CameraOut.from_camera(await get_scoped_or_404(session, Camera, camera_id, user, "camera"))


@router.patch("/{camera_id}", response_model=CameraOut)
async def update_camera(camera_id: uuid.UUID, body: CameraUpdate, request: Request,
                        user: CurrentUser = Depends(writer), session: AsyncSession = Depends(get_session)):
    cam = await get_scoped_or_404(session, Camera, camera_id, user, "camera")
    changes = body.model_dump(exclude_unset=True)
    if "source_url" in changes:
        url = changes.pop("source_url")
        cam.source_url_encrypted = encrypt_secret(url) if url else None
        changes_logged = ["source_url"]
    else:
        changes_logged = []
    for field, value in changes.items():
        setattr(cam, field, value)
    if cam.mode == "live" and not cam.frigate_name:
        raise ApiError(422, "validation", "Validation failed", detail="frigate_name is required for live cameras")
    await flush_or_conflict(session, DUPLICATE)
    await session.refresh(cam)
    await record_audit(session, action="camera.update", customer_id=cam.customer_id, actor=user,
                       entity_type="camera", entity_id=cam.id,
                       details={"fields": sorted(changes) + changes_logged}, ip=client_ip(request))
    return CameraOut.from_camera(cam)


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(camera_id: uuid.UUID, request: Request, user: CurrentUser = Depends(writer),
                        session: AsyncSession = Depends(get_session)):
    cam = await get_scoped_or_404(session, Camera, camera_id, user, "camera")
    await record_audit(session, action="camera.delete", customer_id=cam.customer_id, actor=user,
                       entity_type="camera", entity_id=cam.id, details={"name": cam.name}, ip=client_ip(request))
    await session.delete(cam)
    return Response(status_code=204)

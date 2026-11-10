"""Resumable uploads, tus 1.0.0 (creation + termination extensions)."""
import base64
import binascii
import uuid
from datetime import UTC

import anyio
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.audit.service import record_audit
from app.auth.deps import CurrentUser, require_roles
from app.common.errors import ApiError, not_found, problem_response
from app.common.request import client_ip
from app.config import get_settings
from app.db import get_session
from app.models import Session, SessionVideo
from app.sessions.service import UPLOADABLE, list_videos, reorder_by_creation_time, session_prefix
from app.storage.base import Storage, get_storage
from app.tenancy.scoping import get_scoped_or_404, scoped
from app.uploads import staging
from app.video.ffmpeg import VideoError, probe

TUS_VERSION = "1.0.0"
UPLOADS_PATH = "/api/v1/uploads"
NOT_A_VIDEO = "This file isn't a readable video."

router = APIRouter(prefix="/uploads", tags=["uploads"])
writer = require_roles("customer_admin", "operator")


class TusMiddleware:
    """Stamps Tus-Resumable on every /uploads response and rejects other protocol versions (412)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(UPLOADS_PATH):
            await self.app(scope, receive, send)
            return
        header = {"Tus-Resumable": TUS_VERSION}
        headers = dict(scope["headers"])
        if scope["method"] != "OPTIONS" and headers.get(b"tus-resumable", b"").decode() != TUS_VERSION:
            response = problem_response(412, "unsupported-tus-version", "Precondition failed",
                                        f"Tus-Resumable: {TUS_VERSION} is required",
                                        headers={**header, "Tus-Version": TUS_VERSION})
            await response(scope, receive, send)
            return

        async def send_with_tus(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"tus-resumable", TUS_VERSION.encode()))
            await send(message)

        await self.app(scope, receive, send_with_tus)


def _parse_metadata(raw: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in (raw or "").split(","):
        key, _, value = pair.strip().partition(" ")
        if not key:
            continue
        try:
            out[key] = base64.b64decode(value.strip(), validate=True).decode() if value.strip() else ""
        except (binascii.Error, UnicodeDecodeError) as e:
            raise ApiError(400, "invalid-metadata", "Invalid Upload-Metadata", f"{key} is not valid base64") from e
    return out


def _int_header(request: Request, name: str) -> int:
    raw = request.headers.get(name)
    try:
        value = int(raw) if raw is not None else -1
    except ValueError:
        value = -1
    if value < 0:
        raise ApiError(400, "invalid-header", "Invalid header", f"{name} must be a non-negative integer")
    return value


async def _renumber(db: AsyncSession, session_id: uuid.UUID) -> None:
    for position, video in enumerate(await list_videos(db, session_id)):
        video.position = position
    await db.flush()


async def _lock_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    """Row lock on the session: every position-changing step (create, complete, delete) takes it first,
    so they run one at a time per session and always lock session before video rows."""
    await db.execute(select(Session.id).where(Session.id == session_id).with_for_update())


async def _get_video(db: AsyncSession, video_id: uuid.UUID, user: CurrentUser, *, lock: bool = False) -> SessionVideo:
    stmt = scoped(select(SessionVideo).where(SessionVideo.id == video_id), SessionVideo, user)
    if lock:
        stmt = stmt.with_for_update()
    video = (await db.execute(stmt)).scalar_one_or_none()
    if video is None:
        raise not_found("upload")
    return video


@router.options("", status_code=204)
async def tus_options() -> Response:
    return Response(status_code=204, headers={
        "Tus-Version": TUS_VERSION, "Tus-Extension": "creation,termination",
        "Tus-Max-Size": str(get_settings().max_upload_bytes)})


@router.post("", status_code=201)
async def create_upload(request: Request, user: CurrentUser = Depends(writer),
                        db: AsyncSession = Depends(get_session)) -> Response:
    length = _int_header(request, "Upload-Length")
    if length > get_settings().max_upload_bytes:
        raise ApiError(413, "too-large", "Upload too large",
                       f"Uploads are limited to {get_settings().max_upload_bytes} bytes")
    if length == 0:
        raise ApiError(400, "invalid-header", "Invalid header", "Upload-Length must be greater than zero")
    meta = _parse_metadata(request.headers.get("Upload-Metadata"))
    try:
        session_id = uuid.UUID(meta["session_id"])
    except (KeyError, ValueError) as e:
        raise ApiError(422, "validation", "Validation failed",
                       errors=[{"field": "session_id", "message": "Upload-Metadata must include a valid session_id"}]
                       ) from e
    s = await get_scoped_or_404(db, Session, session_id, user, "session")
    await _lock_session(db, s.id)  # serialise position assignment within the session
    if s.status not in UPLOADABLE:
        raise ApiError(409, "conflict", "Conflict", f"A session that is {s.status} cannot take new videos")
    video_id = uuid.uuid4()
    count = len(await list_videos(db, s.id))
    video = SessionVideo(
        id=video_id, customer_id=s.customer_id, session_id=s.id, position=count,
        original_filename=(meta.get("filename") or None) and meta["filename"][:255],
        size_bytes=length, original_key=f"{session_prefix(s)}/source/{video_id}.mp4", status="uploading")
    db.add(video)
    await db.flush()
    staging.create_staging(video_id)
    return Response(status_code=201, headers={"Location": f"{UPLOADS_PATH}/{video_id}"})


@router.head("/{video_id}")
async def upload_status(video_id: uuid.UUID, user: CurrentUser = Depends(writer),
                        db: AsyncSession = Depends(get_session)) -> Response:
    video = await _get_video(db, video_id, user)
    if video.status == "failed":
        raise ApiError(410, "gone", "Gone", "This upload failed; remove it and upload again")
    offset = video.size_bytes if video.status != "uploading" else staging.staged_size(video.id)
    return Response(status_code=200, headers={
        "Upload-Offset": str(offset), "Upload-Length": str(video.size_bytes), "Cache-Control": "no-store"})


@router.patch("/{video_id}")
async def upload_chunk(video_id: uuid.UUID, request: Request, user: CurrentUser = Depends(writer),
                       db: AsyncSession = Depends(get_session), storage: Storage = Depends(get_storage)) -> Response:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/offset+octet-stream":
        raise ApiError(415, "unsupported-media-type", "Unsupported media type",
                       "Content-Type must be application/offset+octet-stream")
    offset = _int_header(request, "Upload-Offset")
    video = await _get_video(db, video_id, user)
    # Serialise chunks of this one upload with a transaction-scoped advisory lock. Unlike a row lock it never
    # blocks other videos' completions (which renumber sibling rows), so two uploads can run side by side.
    got = (await db.execute(select(func.pg_try_advisory_xact_lock(func.hashtext(str(video.id)))))).scalar_one()
    if not got:
        raise ApiError(409, "conflict", "Conflict", "Another request is already writing to this upload")
    await db.refresh(video)
    if video.status != "uploading":
        raise ApiError(409, "conflict", "Conflict", f"This upload is {video.status}")
    on_disk = staging.staged_size(video.id)
    if offset != on_disk:
        raise ApiError(409, "offset-mismatch", "Offset mismatch", f"Server offset is {on_disk}, got {offset}")

    path = staging.staging_path(video.id)
    position = on_disk
    overflow = False
    with path.open("ab") as f:
        async for chunk in request.stream():
            if position + len(chunk) > video.size_bytes:
                overflow = True
                break
            f.write(chunk)
            position += len(chunk)
        await anyio.to_thread.run_sync(staging.fsync_file, f)
    if overflow:
        raise ApiError(400, "exceeds-length", "Bad request", "The upload would exceed Upload-Length")
    headers = {"Upload-Offset": str(position)}
    if position < video.size_bytes:
        return Response(status_code=204, headers=headers)

    # Completion: session lock first (same order as POST/DELETE), so completions in a session run one at a time.
    await _lock_session(db, video.session_id)
    try:
        info = await anyio.to_thread.run_sync(probe, path)
    except VideoError:
        video.status, video.error = "failed", NOT_A_VIDEO
        staging.remove_staging(video.id)
        return problem_response(422, "not-a-video", "Not a video", NOT_A_VIDEO)  # returned, so the failure commits
    size = await anyio.to_thread.run_sync(storage.import_file, video.original_key, path)
    video.size_bytes = size
    video.duration_ms, video.fps, video.width, video.height = info.duration_ms, info.fps, info.width, info.height
    video.creation_time = info.creation_time.astimezone(UTC) if info.creation_time else None
    video.status = "uploaded"
    await db.flush()
    await reorder_by_creation_time(db, video.session_id)
    await record_audit(db, action="session.upload", customer_id=video.customer_id, actor=user,
                       entity_type="session", entity_id=video.session_id, ip=client_ip(request),
                       details={"video_id": str(video.id), "filename": video.original_filename, "size_bytes": size})
    return Response(status_code=204, headers=headers)


@router.delete("/{video_id}", status_code=204)
async def delete_upload(video_id: uuid.UUID, request: Request, user: CurrentUser = Depends(writer),
                        db: AsyncSession = Depends(get_session), storage: Storage = Depends(get_storage)) -> Response:
    video = await _get_video(db, video_id, user)
    await _lock_session(db, video.session_id)
    video = await _get_video(db, video_id, user, lock=True)
    s = await db.get(Session, video.session_id)
    if video.status not in ("uploading", "failed") and s.status in ("queued", "processing"):
        raise ApiError(409, "conflict", "Conflict", "This video is being processed; wait for it to finish")
    staging.remove_staging(video.id)
    if video.status in ("uploaded", "processed"):
        await anyio.to_thread.run_sync(storage.delete, video.original_key)
    await db.delete(video)
    await db.flush()
    await _renumber(db, video.session_id)
    await record_audit(db, action="session.video_delete", customer_id=video.customer_id, actor=user,
                       entity_type="session", entity_id=video.session_id, ip=client_ip(request),
                       details={"video_id": str(video.id), "filename": video.original_filename})
    return Response(status_code=204)

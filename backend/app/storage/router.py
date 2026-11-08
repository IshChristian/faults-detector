import mimetypes

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.common.errors import ApiError, not_found
from app.storage.base import Storage, get_storage, validate_key
from app.storage.signing import verify_media_signature

router = APIRouter(tags=["media"])


@router.get("/media/{key:path}")
async def get_media(key: str, exp: int = Query(0), sig: str = Query(""),
                    storage: Storage = Depends(get_storage)):
    validate_key(key)
    if not verify_media_signature(key, exp, sig):
        raise ApiError(403, "invalid-signature", "Invalid or expired link")
    path = storage.local_path(key)
    if path is None or not path.is_file():
        raise not_found("media")
    media_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    # FileResponse handles HTTP Range (206), which video seeking needs.
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})

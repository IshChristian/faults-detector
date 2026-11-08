import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Mode = Literal["live", "upload"]
SourceType = Literal["rtsp", "usb", "phone", "screen", "file"]


class CameraCreate(BaseModel):
    site_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    mode: Mode
    source_type: SourceType
    source_url: str | None = Field(None, max_length=2048)  # write-only; stored encrypted
    frigate_name: str | None = Field(None, min_length=1, max_length=64)
    resolution: str | None = Field(None, max_length=20)
    fps: int = Field(5, ge=1, le=30)

    @model_validator(mode="after")
    def _live_needs_frigate_name(self):
        if self.mode == "live" and not self.frigate_name:
            raise ValueError("frigate_name is required for live cameras")
        return self


class CameraUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    mode: Mode | None = None
    source_type: SourceType | None = None
    source_url: str | None = Field(None, max_length=2048)
    frigate_name: str | None = Field(None, max_length=64)
    resolution: str | None = Field(None, max_length=20)
    fps: int | None = Field(None, ge=1, le=30)
    ai_enabled: bool | None = None


class CameraOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    site_id: uuid.UUID
    name: str
    mode: str
    source_type: str
    source_url_set: bool
    frigate_name: str | None
    resolution: str | None
    fps: int
    ai_enabled: bool
    status: str
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_camera(cls, cam) -> "CameraOut":
        return cls(id=cam.id, customer_id=cam.customer_id, site_id=cam.site_id, name=cam.name, mode=cam.mode,
                   source_type=cam.source_type, source_url_set=cam.source_url_encrypted is not None,
                   frigate_name=cam.frigate_name, resolution=cam.resolution, fps=cam.fps,
                   ai_enabled=cam.ai_enabled, status=cam.status, last_seen_at=cam.last_seen_at,
                   created_at=cam.created_at, updated_at=cam.updated_at)

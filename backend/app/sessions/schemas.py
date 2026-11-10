import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SessionType = Literal["training", "match"]
SessionStatus = Literal["uploading", "queued", "processing", "ready", "failed"]


class SessionCreate(BaseModel):
    site_id: uuid.UUID
    source_id: uuid.UUID
    type: SessionType
    starts_at: datetime
    title: str | None = Field(None, max_length=255)
    squad: str | None = Field(None, max_length=100)
    sprint_threshold_kmh: float | None = Field(None, ge=5, le=40)


class SessionUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    squad: str | None = Field(None, max_length=100)
    starts_at: datetime | None = None
    type: SessionType | None = None
    sprint_threshold_kmh: float | None = Field(None, ge=5, le=40)

    @model_validator(mode="after")
    def _not_nullable(self):
        for field in ("starts_at", "type", "sprint_threshold_kmh"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class VideoOrder(BaseModel):
    video_ids: list[uuid.UUID]


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    original_filename: str | None
    size_bytes: int
    duration_ms: int | None
    fps: float | None
    width: int | None
    height: int | None
    creation_time: datetime | None
    status: str
    error: str | None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    site_id: uuid.UUID
    source_id: uuid.UUID
    type: str
    starts_at: datetime
    title: str | None
    squad: str | None
    status: str
    progress: int
    stage: str | None
    error: str | None
    sync_offset_ms: int
    sprint_threshold_kmh: float
    calibration_id: uuid.UUID | None
    quality: dict | None
    created_at: datetime
    updated_at: datetime


class SessionDetail(SessionOut):
    videos: list[VideoOut]

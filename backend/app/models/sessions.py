"""ORM mapping for sessions and their videos, calibrations and tracks (migration 0003)."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._types import created_at, updated_at, uuid_pk


def _customer_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"))


class Calibration(Base):
    __tablename__ = "calibrations"

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = _customer_fk()
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"))
    image_points: Mapped[list] = mapped_column(JSONB)
    pitch_points: Mapped[list] = mapped_column(JSONB)
    pitch_length_m: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    pitch_width_m: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = _customer_fk()
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="RESTRICT"))
    type: Mapped[str] = mapped_column(String(10))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    title: Mapped[str | None] = mapped_column(String(255))
    squad: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(12), server_default="uploading")
    progress: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    stage: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    sync_offset_ms: Mapped[int] = mapped_column(Integer, server_default="0")
    sprint_threshold_kmh: Mapped[Decimal] = mapped_column(Numeric(4, 1), server_default="19.0")
    calibration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibrations.id", ondelete="SET NULL"))
    quality: Mapped[dict | None] = mapped_column(JSONB)
    summary_key: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class SessionVideo(Base):
    __tablename__ = "session_videos"

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = _customer_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(SmallInteger)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    original_key: Mapped[str] = mapped_column(Text)
    proxy_key: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    creation_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), server_default="uploading")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class SessionTrack(Base):
    __tablename__ = "session_tracks"

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = _customer_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    track_id: Mapped[int] = mapped_column(Integer)
    cls: Mapped[str | None] = mapped_column(String(10))
    team: Mapped[str | None] = mapped_column(String(5))
    team_corrected: Mapped[bool] = mapped_column(Boolean, server_default="false")
    on_pitch: Mapped[bool | None] = mapped_column(Boolean)
    frames_count: Mapped[int] = mapped_column(Integer)
    first_ms: Mapped[int] = mapped_column(Integer)
    last_ms: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict | None] = mapped_column(JSONB)

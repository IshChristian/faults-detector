"""ORM mapping for cameras (sources). Columns from migration 0001 plus `mode` from 0002."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._types import created_at, updated_at, uuid_pk


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"))
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    frigate_name: Mapped[str | None] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(10), server_default="live")
    source_type: Mapped[str] = mapped_column(String(20))
    source_url_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    resolution: Mapped[str | None] = mapped_column(String(20))
    fps: Mapped[int] = mapped_column(SmallInteger, server_default="5")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    status: Mapped[str] = mapped_column(String(20), server_default="offline")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

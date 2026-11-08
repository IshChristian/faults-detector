import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _check_timezone(v: str | None) -> str | None:
    if v is None:
        return v
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown timezone: {v}") from e
    return v


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    location: str | None = None
    timezone: str = "Africa/Kigali"
    business_hours: dict | None = None
    customer_id: uuid.UUID | None = None

    _tz = field_validator("timezone")(_check_timezone)


class SiteUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    location: str | None = None
    timezone: str | None = None
    business_hours: dict | None = None

    _tz = field_validator("timezone")(_check_timezone)


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    name: str
    location: str | None
    timezone: str
    business_hours: dict | None
    created_at: datetime
    updated_at: datetime

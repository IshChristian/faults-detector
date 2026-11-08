import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AssignableRole = Literal["customer_admin", "operator", "viewer"]  # super_admin only via the CLI


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=10, max_length=256)
    role: AssignableRole
    telegram_chat_id: str | None = Field(None, max_length=64)
    phone: str | None = Field(None, max_length=50)
    customer_id: uuid.UUID | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=255)
    password: str | None = Field(None, min_length=10, max_length=256)
    role: AssignableRole | None = None
    telegram_chat_id: str | None = Field(None, max_length=64)
    phone: str | None = Field(None, max_length=50)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID | None
    email: str
    full_name: str
    role: str
    telegram_chat_id: str | None
    phone: str | None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime

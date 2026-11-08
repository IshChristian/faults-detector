"""Cursor pagination: ?limit= (default 50, max 200) and ?cursor=, newest first."""
import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import ApiError

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None


def limit_param(limit: int = Query(50, ge=1, le=200)) -> int:
    return limit


def encode_cursor(created_at: datetime, id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "id": str(id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["id"])
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError) as e:
        raise ApiError(400, "invalid-cursor", "Invalid cursor", "The cursor is malformed") from e


async def paginate(session: AsyncSession, stmt: Select, model, limit: int,
                   cursor: str | None) -> tuple[list, str | None]:
    """Run `stmt` ordered by (created_at, id) descending; returns (items, next_cursor)."""
    if cursor:
        t, i = decode_cursor(cursor)
        stmt = stmt.where(tuple_(model.created_at, model.id) < tuple_(t, i))
    stmt = stmt.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars())
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        return rows, encode_cursor(last.created_at, last.id)
    return rows, None

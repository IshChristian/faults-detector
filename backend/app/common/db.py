from collections.abc import Awaitable, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import conflict


async def flush_or_conflict(session: AsyncSession, detail: str) -> None:
    """Flush inside a savepoint; a unique-constraint violation becomes a 409 instead of a 500."""
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as e:
        if getattr(e.orig, "sqlstate", None) == "23505" or "unique" in str(e.orig).lower():
            raise conflict(detail) from e
        raise

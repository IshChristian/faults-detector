"""Bridge from synchronous RQ jobs to the async database layer."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

T = TypeVar("T")


def run_async(fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run `fn` with a fresh session on its own NullPool engine, commit, and dispose.

    A job gets an engine of its own because `asyncio.run` starts a new event loop and a pooled connection
    belongs to the loop that opened it. The session is rolled back when `fn` raises.
    """

    async def main() -> T:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await fn(session)
                await session.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(main())

"""Valkey (Redis-protocol) client for the API: rate limits, rule state, pub/sub."""
from functools import lru_cache

from redis.asyncio import Redis

from app.config import get_settings


@lru_cache
def _client() -> Redis:
    return Redis.from_url(get_settings().redis_url)


def get_redis() -> Redis:
    """FastAPI dependency. Tests override it with fakeredis."""
    return _client()

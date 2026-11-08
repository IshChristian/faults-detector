from redis.asyncio import Redis

from app.common.errors import ApiError

WINDOW_SECONDS = 60


async def check_login_rate(redis: Redis, ip: str, email: str, limit: int) -> None:
    """Count this attempt; refuse once more than `limit` attempts arrive within a minute."""
    key = f"rl:login:{ip}:{email.strip().lower()}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, WINDOW_SECONDS)
    if count > limit:
        raise ApiError(429, "rate-limited", "Too many login attempts",
                       "Too many login attempts. Wait a minute and try again.")

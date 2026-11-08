import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import (DUMMY_HASH, create_access_token, hash_refresh_token, new_refresh_token,
                               verify_password)
from app.common.errors import ApiError
from app.config import get_settings
from app.models import Customer, RefreshToken, User

INVALID_CREDENTIALS = ApiError(401, "invalid-credentials", "Invalid email or password")
INVALID_REFRESH = ApiError(401, "invalid-refresh-token", "Session expired. Please log in again.")


async def find_user_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(func.lower(User.email) == email.strip().lower())
    return (await session.execute(stmt)).scalar_one_or_none()


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    """Return the active user, or raise the same 401 for unknown email, wrong password or inactive user."""
    user = await find_user_by_email(session, email)
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or not user.is_active:
        raise INVALID_CREDENTIALS
    return user


async def issue_tokens(session: AsyncSession, user: User) -> tuple[str, str]:
    raw, token_hash = new_refresh_token()
    days = get_settings().refresh_token_days
    session.add(RefreshToken(user_id=user.id, token_hash=token_hash,
                             expires_at=datetime.now(UTC) + timedelta(days=days)))
    await session.flush()
    return create_access_token(user), raw


async def revoke_all(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now()))


async def rotate(session: AsyncSession, raw: str) -> tuple[User, str, str]:
    """Exchange a refresh token for a new pair. Reusing a rotated token revokes every token of that user."""
    stmt = (select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
            .with_for_update())
    token = (await session.execute(stmt)).scalar_one_or_none()
    if token is None:
        raise INVALID_REFRESH
    if token.revoked_at is not None:
        # Theft detection: a rotated token came back. Kill the whole family, keep that change.
        await revoke_all(session, token.user_id)
        await session.commit()
        raise INVALID_REFRESH
    if token.expires_at <= datetime.now(UTC):
        raise INVALID_REFRESH
    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise INVALID_REFRESH
    token.revoked_at = datetime.now(UTC)
    access, new_raw = await issue_tokens(session, user)
    return user, access, new_raw


async def revoke(session: AsyncSession, raw: str) -> User | None:
    """Revoke one refresh token; returns its owner if the token was live."""
    user_id = (await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
        .returning(RefreshToken.user_id))).scalar_one_or_none()
    return await session.get(User, user_id) if user_id else None


async def customer_industry(session: AsyncSession, user: User) -> str | None:
    if user.customer_id is None:
        return None
    return (await session.execute(select(Customer.industry).where(Customer.id == user.customer_id))).scalar()

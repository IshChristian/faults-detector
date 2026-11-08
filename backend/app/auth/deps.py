import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_access_token
from app.common.errors import ApiError, forbidden
from app.db import get_session
from app.models import User

ROLES = ("super_admin", "customer_admin", "operator", "viewer")


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    customer_id: uuid.UUID | None
    role: str
    email: str

    @property
    def is_super_admin(self) -> bool:
        return self.role == "super_admin"


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "unauthorized", "Authentication required")
    return token


async def get_current_user(request: Request, session: AsyncSession = Depends(get_session)) -> CurrentUser:
    claims = decode_access_token(_bearer_token(request))
    try:
        user_id = uuid.UUID(claims["sub"])
    except ValueError as e:
        raise ApiError(401, "invalid-token", "Invalid or expired token") from e
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise ApiError(401, "invalid-token", "Invalid or expired token")
    # Role and tenant come from the database, not the token, so changes apply immediately.
    return CurrentUser(id=user.id, customer_id=user.customer_id, role=user.role, email=user.email)


def require_roles(*roles: str) -> Callable:
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role != "super_admin" and user.role not in roles:
            raise forbidden()
        return user
    return _check

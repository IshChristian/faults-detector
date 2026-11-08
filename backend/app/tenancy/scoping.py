"""Tenant isolation helpers. Another customer's resource is always a 404, never a 403."""
import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.common.errors import ApiError, not_found


def scoped(stmt: Select, model, user: CurrentUser) -> Select:
    if user.is_super_admin:
        return stmt
    return stmt.where(model.customer_id == user.customer_id)


async def get_scoped_or_404(session: AsyncSession, model, id: uuid.UUID, user: CurrentUser, entity: str):
    obj = (await session.execute(scoped(select(model).where(model.id == id), model, user))).scalar_one_or_none()
    if obj is None:
        raise not_found(entity)
    return obj


def resolve_customer_id(user: CurrentUser, requested: uuid.UUID | None) -> uuid.UUID:
    """super_admin must name the customer; everyone else always acts for their own customer."""
    if user.is_super_admin:
        if requested is None:
            raise ApiError(422, "validation", "Validation failed", detail="customer_id is required")
        return requested
    assert user.customer_id is not None
    return user.customer_id

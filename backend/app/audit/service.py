"""Audit trail (11-security-privacy-policy.md): logins, exports, reviews, config changes."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.models import AuditLog


async def record_audit(session: AsyncSession, *, action: str, customer_id: uuid.UUID | None,
                       actor: CurrentUser | None = None, entity_type: str | None = None,
                       entity_id: uuid.UUID | None = None, details: dict | None = None,
                       ip: str | None = None) -> None:
    """Add an audit row to the current transaction. The caller's commit persists it."""
    session.add(AuditLog(
        customer_id=customer_id,
        actor_user_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        ip_address=ip,
    ))

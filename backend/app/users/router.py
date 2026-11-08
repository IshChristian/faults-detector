import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.deps import CurrentUser, require_roles
from app.auth.security import hash_password
from app.auth.service import find_user_by_email, revoke_all
from app.common.errors import conflict, not_found
from app.common.pagination import Page, limit_param, paginate
from app.common.request import client_ip
from app.db import get_session
from app.models import Customer, User
from app.tenancy.scoping import get_scoped_or_404, resolve_customer_id, scoped
from app.users.schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])
admin = require_roles("customer_admin")


@router.get("", response_model=Page[UserOut])
async def list_users(limit: int = Depends(limit_param), cursor: str | None = Query(None),
                     user: CurrentUser = Depends(admin), session: AsyncSession = Depends(get_session)):
    items, next_cursor = await paginate(session, scoped(select(User), User, user), User, limit, cursor)
    return Page[UserOut](items=[UserOut.model_validate(u) for u in items], next_cursor=next_cursor)


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, request: Request, user: CurrentUser = Depends(admin),
                      session: AsyncSession = Depends(get_session)):
    customer_id = resolve_customer_id(user, body.customer_id)
    if await session.get(Customer, customer_id) is None:
        raise not_found("customer")
    email = body.email.strip().lower()
    if await find_user_by_email(session, email):
        raise conflict("A user with this email already exists")
    new = User(customer_id=customer_id, email=email, full_name=body.full_name,
               password_hash=hash_password(body.password), role=body.role,
               telegram_chat_id=body.telegram_chat_id, phone=body.phone)
    session.add(new)
    await session.flush()
    await session.refresh(new)
    await record_audit(session, action="user.create", customer_id=customer_id, actor=user, entity_type="user",
                       entity_id=new.id, details={"email": email, "role": body.role}, ip=client_ip(request))
    return new


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, user: CurrentUser = Depends(admin),
                   session: AsyncSession = Depends(get_session)):
    return await get_scoped_or_404(session, User, user_id, user, "user")


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request, user: CurrentUser = Depends(admin),
                      session: AsyncSession = Depends(get_session)):
    target = await get_scoped_or_404(session, User, user_id, user, "user")
    changes = body.model_dump(exclude_unset=True)
    password = changes.pop("password", None)
    for field, value in changes.items():
        setattr(target, field, value)
    if password:
        target.password_hash = hash_password(password)
        await revoke_all(session, target.id)  # a password change ends existing sessions
    await session.flush()
    await session.refresh(target)
    fields = sorted(changes) + (["password"] if password else [])
    await record_audit(session, action="user.update", customer_id=target.customer_id, actor=user, entity_type="user",
                       entity_id=target.id, details={"fields": fields}, ip=client_ip(request))
    return target


@router.delete("/{user_id}", status_code=204)
async def deactivate_user(user_id: uuid.UUID, request: Request, user: CurrentUser = Depends(admin),
                          session: AsyncSession = Depends(get_session)):
    target = await get_scoped_or_404(session, User, user_id, user, "user")
    if target.id == user.id:
        raise conflict("You cannot deactivate your own account")
    target.is_active = False  # rows are kept so audit and review references stay valid
    await revoke_all(session, target.id)
    await record_audit(session, action="user.delete", customer_id=target.customer_id, actor=user, entity_type="user",
                       entity_id=target.id, ip=client_ip(request))
    return Response(status_code=204)

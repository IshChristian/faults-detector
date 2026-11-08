from fastapi import APIRouter, Body, Cookie, Depends, Request, Response
from redis.asyncio import Redis
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth import service
from app.auth.deps import CurrentUser, get_current_user
from app.auth.ratelimit import check_login_rate
from app.auth.schemas import LoginRequest, RefreshRequest, TokenResponse, UserOut
from app.cache import get_redis
from app.common.errors import ApiError
from app.config import get_settings
from app.db import get_session
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "vg_refresh"
COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(COOKIE_NAME, raw, max_age=s.refresh_token_days * 86400, path=COOKIE_PATH,
                        httponly=True, samesite="strict", secure=s.cookie_secure)


async def _user_out(session: AsyncSession, user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role,
                   customer_id=user.customer_id, customer_industry=await service.customer_industry(session, user))


def _actor(user: User) -> CurrentUser:
    return CurrentUser(id=user.id, customer_id=user.customer_id, role=user.role, email=user.email)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, response: Response,
                session: AsyncSession = Depends(get_session), redis: Redis = Depends(get_redis)):
    s = get_settings()
    await check_login_rate(redis, _client_ip(request), body.email, s.login_rate_limit_per_minute)
    ip = _client_ip(request)
    try:
        user = await service.authenticate(session, body.email, body.password)
    except ApiError:
        # Keep the failed attempt even though the request fails.
        await record_audit(session, action="auth.login_failed", customer_id=None,
                           details={"email": body.email.strip().lower()}, ip=ip)
        await session.commit()
        raise
    access, raw = await service.issue_tokens(session, user)
    user.last_login_at = func.now()
    await record_audit(session, action="auth.login", customer_id=user.customer_id, actor=_actor(user), ip=ip)
    await session.flush()
    await session.refresh(user)
    _set_refresh_cookie(response, raw)
    return TokenResponse(access_token=access, refresh_token=raw, user=await _user_out(session, user))


def _raw_refresh(body: RefreshRequest | None, cookie: str | None) -> str:
    raw = (body.refresh_token if body else None) or cookie
    if not raw:
        raise ApiError(401, "invalid-refresh-token", "Session expired. Please log in again.")
    return raw


@router.post("/refresh", response_model=TokenResponse)
async def refresh(response: Response, body: RefreshRequest | None = Body(None),
                  vg_refresh: str | None = Cookie(None), session: AsyncSession = Depends(get_session)):
    user, access, raw = await service.rotate(session, _raw_refresh(body, vg_refresh))
    _set_refresh_cookie(response, raw)
    return TokenResponse(access_token=access, refresh_token=raw, user=await _user_out(session, user))


@router.post("/logout", status_code=204)
async def logout(request: Request, body: RefreshRequest | None = Body(None), vg_refresh: str | None = Cookie(None),
                 session: AsyncSession = Depends(get_session)):
    raw = (body.refresh_token if body else None) or vg_refresh
    if raw and (user := await service.revoke(session, raw)):
        await record_audit(session, action="auth.logout", customer_id=user.customer_id, actor=_actor(user),
                           ip=_client_ip(request))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    return response


@router.get("/me", response_model=UserOut)
async def me(current: CurrentUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, current.id)
    return await _user_out(session, user)

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.deps import CurrentUser, get_current_user, require_roles
from app.common.errors import not_found
from app.common.pagination import Page, limit_param, paginate
from app.common.request import client_ip
from app.db import get_session
from app.models import Customer, Site
from app.sites.schemas import SiteCreate, SiteOut, SiteUpdate
from app.tenancy.scoping import get_scoped_or_404, resolve_customer_id, scoped

router = APIRouter(prefix="/sites", tags=["sites"])
writer = require_roles("customer_admin")


@router.get("", response_model=Page[SiteOut])
async def list_sites(limit: int = Depends(limit_param), cursor: str | None = Query(None),
                     user: CurrentUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    items, next_cursor = await paginate(session, scoped(select(Site), Site, user), Site, limit, cursor)
    return Page[SiteOut](items=[SiteOut.model_validate(s) for s in items], next_cursor=next_cursor)


@router.post("", response_model=SiteOut, status_code=201)
async def create_site(body: SiteCreate, request: Request, user: CurrentUser = Depends(writer),
                      session: AsyncSession = Depends(get_session)):
    customer_id = resolve_customer_id(user, body.customer_id)
    if await session.get(Customer, customer_id) is None:
        raise not_found("customer")
    site = Site(customer_id=customer_id, **body.model_dump(exclude={"customer_id"}))
    session.add(site)
    await session.flush()
    await session.refresh(site)
    await record_audit(session, action="site.create", customer_id=customer_id, actor=user, entity_type="site",
                       entity_id=site.id, details={"name": site.name}, ip=client_ip(request))
    return site


@router.get("/{site_id}", response_model=SiteOut)
async def get_site(site_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                   session: AsyncSession = Depends(get_session)):
    return await get_scoped_or_404(session, Site, site_id, user, "site")


@router.patch("/{site_id}", response_model=SiteOut)
async def update_site(site_id: uuid.UUID, body: SiteUpdate, request: Request, user: CurrentUser = Depends(writer),
                      session: AsyncSession = Depends(get_session)):
    site = await get_scoped_or_404(session, Site, site_id, user, "site")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(site, field, value)
    await session.flush()
    await session.refresh(site)
    await record_audit(session, action="site.update", customer_id=site.customer_id, actor=user, entity_type="site",
                       entity_id=site.id, details={"fields": sorted(changes)}, ip=client_ip(request))
    return site


@router.delete("/{site_id}", status_code=204)
async def delete_site(site_id: uuid.UUID, request: Request, user: CurrentUser = Depends(writer),
                      session: AsyncSession = Depends(get_session)):
    site = await get_scoped_or_404(session, Site, site_id, user, "site")
    await record_audit(session, action="site.delete", customer_id=site.customer_id, actor=user, entity_type="site",
                       entity_id=site.id, details={"name": site.name}, ip=client_ip(request))
    await session.delete(site)
    return Response(status_code=204)

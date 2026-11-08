import uuid

import pytest
from sqlalchemy import select

from app.auth.deps import CurrentUser
from app.common.errors import ApiError
from app.models import Site
from app.tenancy.scoping import get_scoped_or_404, resolve_customer_id, scoped


def _cu(customer_id, role="customer_admin"):
    return CurrentUser(id=uuid.uuid4(), customer_id=customer_id, role=role, email="x@x.rw")


async def _two_customers_with_sites(db_session, make_customer):
    a, b = await make_customer(), await make_customer()
    sa, sb = Site(customer_id=a.id, name="A"), Site(customer_id=b.id, name="B")
    db_session.add_all([sa, sb])
    await db_session.flush()
    return a, b, sa, sb


async def test_scoped_filters_other_customers(db_session, make_customer):
    a, b, sa, sb = await _two_customers_with_sites(db_session, make_customer)
    ids = set((await db_session.execute(scoped(select(Site.id), Site, _cu(a.id)))).scalars())
    assert sa.id in ids and sb.id not in ids
    all_ids = set((await db_session.execute(scoped(select(Site.id), Site, _cu(None, "super_admin")))).scalars())
    assert {sa.id, sb.id} <= all_ids


async def test_get_scoped_or_404_hides_other_customer(db_session, make_customer):
    a, b, sa, sb = await _two_customers_with_sites(db_session, make_customer)
    assert (await get_scoped_or_404(db_session, Site, sa.id, _cu(a.id), "site")).id == sa.id
    with pytest.raises(ApiError) as e:
        await get_scoped_or_404(db_session, Site, sb.id, _cu(a.id), "site")
    assert e.value.status == 404
    with pytest.raises(ApiError) as e:
        await get_scoped_or_404(db_session, Site, uuid.uuid4(), _cu(a.id), "site")
    assert e.value.status == 404


def test_resolve_customer_id_rules():
    own, other = uuid.uuid4(), uuid.uuid4()
    assert resolve_customer_id(_cu(None, "super_admin"), other) == other
    with pytest.raises(ApiError) as e:
        resolve_customer_id(_cu(None, "super_admin"), None)
    assert e.value.status == 422 and e.value.detail == "customer_id is required"
    assert resolve_customer_id(_cu(own), other) == own
    assert resolve_customer_id(_cu(own), None) == own

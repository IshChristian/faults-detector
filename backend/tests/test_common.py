import uuid
from datetime import datetime, timezone

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import select

from app.common.errors import ApiError, not_found
from app.common.pagination import decode_cursor, encode_cursor, limit_param, paginate
from app.main import create_app
from app.models import Site


@pytest.fixture
async def app_client():
    app = create_app()

    @app.get("/api/v1/_test/missing")
    async def missing():
        raise not_found("site")

    class Body(BaseModel):
        name: str
        count: int

    @app.post("/api/v1/_test/validate")
    async def validate(body: Body):
        return body

    @app.get("/api/v1/_test/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    @app.get("/api/v1/_test/limit")
    async def limit(n: int = Depends(limit_param)):
        return {"limit": n}

    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://test") as c:
        yield c


async def test_api_error_renders_problem_json(app_client):
    r = await app_client.get("/api/v1/_test/missing")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["type"] == "https://visionguard.ai/errors/not-found"
    assert body["status"] == 404
    assert body["title"]


async def test_validation_error_lists_fields(app_client):
    r = await app_client.post("/api/v1/_test/validate", json={"name": "x", "count": "many"})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["type"] == "https://visionguard.ai/errors/validation"
    assert {"field": "body.count", "message": body["errors"][0]["message"]} in body["errors"]


async def test_unhandled_error_is_500_without_internals(app_client):
    r = await app_client.get("/api/v1/_test/boom")
    assert r.status_code == 500
    assert r.json()["type"] == "https://visionguard.ai/errors/internal"
    assert "secret internal detail" not in r.text


async def test_limit_param_bounds(app_client):
    assert (await app_client.get("/api/v1/_test/limit")).json() == {"limit": 50}
    assert (await app_client.get("/api/v1/_test/limit?limit=201")).status_code == 422
    assert (await app_client.get("/api/v1/_test/limit?limit=0")).status_code == 422


def test_cursor_roundtrip():
    t = datetime(2026, 11, 7, 10, 30, 15, 123456, tzinfo=timezone.utc)
    i = uuid.uuid4()
    assert decode_cursor(encode_cursor(t, i)) == (t, i)


@pytest.mark.parametrize("garbage", ["", "not-base64!!", "eyJ4IjoxfQ"])
def test_garbage_cursor_is_400(garbage):
    with pytest.raises(ApiError) as e:
        decode_cursor(garbage)
    assert e.value.status == 400
    assert e.value.slug == "invalid-cursor"


async def test_paginate_walks_all_rows_without_duplicates(db_session, make_customer):
    c = await make_customer()
    # All rows share one created_at (same transaction), so ordering must fall back to id.
    for n in range(7):
        db_session.add(Site(customer_id=c.id, name=f"S{n}"))
    await db_session.flush()
    stmt = select(Site).where(Site.customer_id == c.id)

    seen, sizes, cursor = [], [], None
    while True:
        items, cursor = await paginate(db_session, stmt, Site, limit=3, cursor=cursor)
        sizes.append(len(items))
        seen += [s.id for s in items]
        if cursor is None:
            break
    assert sizes == [3, 3, 1]
    assert len(seen) == len(set(seen)) == 7

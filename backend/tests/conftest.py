"""Shared test fixtures.

Database tests run against a real PostgreSQL. TEST_DATABASE_URL wins; otherwise the URL is
built from POSTGRES_USER/POSTGRES_PASSWORD in the repo-root .env, pointing at the dev
override's published port (127.0.0.1:5433) and the visionguard_test database.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def _test_database_url() -> str:
    if url := os.environ.get("TEST_DATABASE_URL"):
        return url
    env = dotenv_values(REPO_ROOT / ".env")
    user = env.get("POSTGRES_USER") or "visionguard"
    password = quote(env.get("POSTGRES_PASSWORD") or "visionguard", safe="")
    return f"postgresql+asyncpg://{user}:{password}@127.0.0.1:5433/visionguard_test"


TEST_DATABASE_URL = _test_database_url()

# Settings needed by the app under test. Real deployments get these from .env.
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6380/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-0123456789")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.db import get_session  # noqa: E402  (settings env must be set first)
from app.main import create_app  # noqa: E402
from app.models import Customer, User  # noqa: E402


def pytest_collection_modifyitems(items):
    # One event loop for the whole run, so the session-scoped engine can be shared.
    marker = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if pytest_asyncio.is_async_test(item):
            item.add_marker(marker, append=False)


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    """Bring the test database to the latest Alembic revision, once per run."""
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR, env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL}, check=True,
    )
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
async def engine(migrated_database_url):
    eng = create_async_engine(migrated_database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine):
    """A session inside an outer transaction that is rolled back after each test."""
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            if outer.is_active:
                await outer.rollback()


@pytest.fixture
async def client(db_session):
    app = create_app()

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def make_customer(db_session):
    async def _make(**kw) -> Customer:
        kw.setdefault("name", f"Customer {uuid.uuid4().hex[:8]}")
        kw.setdefault("industry", "sports")
        customer = Customer(**kw)
        db_session.add(customer)
        await db_session.flush()
        return customer
    return _make


@pytest.fixture
def make_user(db_session):
    from argon2 import PasswordHasher

    hasher = PasswordHasher()

    async def _make(customer: Customer | None, role: str, email: str | None = None,
                    password: str = "Passw0rd!long", **kw) -> User:
        user = User(
            customer_id=customer.id if customer else None,
            email=email or f"user-{uuid.uuid4().hex[:8]}@example.com",
            full_name=kw.pop("full_name", "Test User"),
            password_hash=hasher.hash(password),
            role=role,
            **kw,
        )
        db_session.add(user)
        await db_session.flush()
        return user
    return _make

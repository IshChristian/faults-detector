# VisionGuard V1 — Plan 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running, tested platform skeleton (backend API with auth, tenancy, sites/users/sources, audit, storage, job queue, and a React dashboard shell) plus the M0 detection benchmark that de-risks upload mode.

**Architecture:** FastAPI (async SQLAlchemy + Alembic) backed by PostgreSQL 16 and Valkey, an RQ worker with `default` and `sessions` queues, and a React + Vite + TypeScript dashboard served by nginx that proxies `/api` to the backend (same origin, so the refresh cookie works). Everything runs from the existing `docker-compose.yml`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 (asyncpg), Alembic, pydantic-settings, PyJWT, argon2-cffi, cryptography (Fernet), rq, pytest + httpx + fakeredis. React 18, Vite, TypeScript, react-router-dom 6, Vitest + Testing Library + MSW, @fontsource/inter. Spike: rfdetr, supervision, opencv-python.

**Spec:** `docs/superpowers/specs/2026-11-07-visionguard-v1-design.md`, plus `05-api-specification.md` (API conventions) and `16-ui-ux-design-document.pdf` (UI tokens and layout).

### Plan series
| Plan | Covers (spec milestones) | Ends with |
|---|---|---|
| **1. Foundation (this)** | M0 + M1 | Login, sites/users/sources CRUD, storage, queue, dashboard shell, benchmark go/no-go |
| 2. Upload pipeline | M2 | Upload → transcode → detect/track → teams → calibration → metrics |
| 3. Review & tagging | M3 | Review screen, tagger, drills, labelling, clips, share links → **academy pilot** |
| 4. Live mode | M4 | Frigate ingestion, rule engine, incidents, Telegram → **live pilot** |
| 5. Relay & hardening | M5 | Relay VPS, retention, backups, exposure hardening, docs update |

## Global Constraints

- Python **3.11** in containers and local dev (the laptop's 3.10 is not used; install 3.11 with `uv`).
- Dependencies shipped in the product must be MIT/BSD/Apache-2.0 licensed. **No Ultralytics packages anywhere.**
- Roles are exactly `super_admin`, `customer_admin`, `operator`, `viewer`. UI shows `operator` as "Coach" for `industry = 'sports'` customers.
- Every customer-owned query is scoped by `customer_id`. Another customer's resource returns **404**, never 403.
- Errors use RFC 9457 problem details: `{"type":"https://visionguard.ai/errors/<slug>","title":...,"status":...,"detail":...}` with media type `application/problem+json`.
- Pagination: `?limit=` (default 50, max 200) and `?cursor=`; response `{"items":[...],"next_cursor":<str|null>}`.
- Access JWT lifetime `ACCESS_TOKEN_MINUTES=15`, refresh `REFRESH_TOKEN_DAYS=7`, refresh tokens rotated on use and stored hashed. Login is limited to **5 attempts per minute per IP+email**.
- Camera `source_url` is write-only: encrypted at rest with `CREDENTIALS_ENCRYPTION_KEY` (Fernet) and never returned. Responses carry `source_url_set: bool`.
- Default timezone `Africa/Kigali`. Coordinates are relative 0–1.
- Host ports: API `8100` → container `8000`, dashboard `8501`. Port 8000 on the host is reserved for Coolify.
- Docker image tags and npm/pip versions are pinned exactly. No `latest`.
- Alembic owns the schema. Nothing else creates tables.
- Design tokens are copied verbatim from the UI/UX doc §12 (`--bg-page: #F4F2EF; --surface: #FFFFFF; --text-primary: #232323; --text-secondary: #6E6A66; --text-muted: #9C968F; --divider: #E7E3DE; --brand: #F26B5B; --brand-soft: #FAD9CE; --brand-blush: #F7E3DC; --success: #3E9B6C; --warning: #E0A63C; --danger: #D64545; --radius-lg: 20px; --radius-md: 14px; --radius-sm: 10px; --shadow-card: 0 10px 30px rgba(35,35,35,0.06); --shadow-float: 0 18px 45px rgba(35,35,35,0.10); --space-1..7: 4/8/12/16/24/32/48px`).
- Fonts are self-hosted (`@fontsource/inter`), because customer boxes may be offline.

## Review Focus

1. **Email case:** logging in as `Coach@Academy.rw` when the account is `coach@academy.rw` succeeds; creating a second user differing only in case fails with 409. → Task 4 and Task 6 tests.
2. **Refresh-token reuse:** reusing a refresh token after it was rotated returns 401 **and** revokes all of that user's refresh tokens (theft detection). → Task 4 test.
3. **Cross-tenant IDs:** GET/PATCH/DELETE of another customer's site, user or camera returns 404, and the list endpoints never include them. → Task 6 tests.
4. **Media path traversal:** a media key containing `..`, a leading `/`, or a backslash is rejected (400) and never reads outside `MEDIA_ROOT`. → Task 7 test.
5. **super_admin on customer-scoped creates:** a super_admin calling `POST /sites` without `customer_id` gets 422; a customer_admin passing a different `customer_id` has it ignored (their own customer is used). → Task 6 tests.

---

### Task 0: Developer machine setup (owner, manual)

Not code. Needed before anything can run.

- [ ] **Step 1: Install Docker Engine + Compose plugin** using `13-installation-guide.md` §2, then log out and back in.
  Verify: `docker run --rm hello-world` prints "Hello from Docker!".
- [ ] **Step 2: Install uv and Python 3.11**
  Run: `curl -LsSf https://astral.sh/uv/install.sh | sh && uv python install 3.11`
  Verify: `uv run --python 3.11 python --version` → `Python 3.11.x`.
- [ ] **Step 3: Node 20** (already present at v20.20.2). Verify: `node --version`.
- [ ] **Step 4: Create `.env`** from `.env.example`, filling `SECRET_KEY`, `CREDENTIALS_ENCRYPTION_KEY`, `POSTGRES_PASSWORD` as described in `13-installation-guide.md` §3.
- [ ] **Step 5: Record a 5-minute test clip** of a training session following the recording guide in spec §7 (phone elevated at the halfway line, whole pitch in frame, 1080p). Save it outside the repo, e.g. `~/vg-footage/test-session.mp4`. Used by Task 13.

---

### Task 1: Backend scaffold and health endpoint

**Files:**
- Create: `backend/pyproject.toml`, `backend/Dockerfile`, `backend/.dockerignore`
- Create: `backend/app/__init__.py`, `backend/app/main.py`, `backend/app/config.py`, `backend/app/health.py`
- Test: `backend/tests/__init__.py`, `backend/tests/test_health.py`

**Interfaces:**
- Produces: `app.main.create_app() -> FastAPI` (all routers mounted under `/api/v1`); `app.config.Settings` (pydantic-settings, env-driven) with fields `database_url: str`, `redis_url: str`, `secret_key: str`, `credentials_encryption_key: str`, `access_token_minutes: int = 15`, `refresh_token_days: int = 7`, `media_root: Path = Path("/app/media")`, `default_timezone: str = "Africa/Kigali"`, `login_rate_limit_per_minute: int = 5`, `cookie_secure: bool = True`; `app.config.get_settings() -> Settings` (lru_cached).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_health.py
async def test_health_returns_ok(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```
Plus a minimal `backend/tests/conftest.py` providing `client` (httpx `AsyncClient` with `ASGITransport(app=create_app())`, base_url `http://test`). Task 2 extends this conftest.

- [ ] **Step 2: Run test to verify it fails**
  Run: `cd backend && uv run pytest tests/test_health.py -v` → FAIL (`ModuleNotFoundError: app`).
- [ ] **Step 3: Implement** `pyproject.toml` (requires-python `==3.11.*`, pinned deps, `[tool.pytest.ini_options] asyncio_mode = "auto"`), `Settings`, `create_app()`, and `GET /api/v1/health → {"status":"ok"}`. Dockerfile: `python:3.11-slim`, installs ffmpeg (needed in Plan 2), runs `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`.
- [ ] **Step 4: Run test to verify it passes** → PASS.
- [ ] **Step 5: Commit** `git add backend && git commit -m "feat(backend): scaffold FastAPI app with health endpoint"`

---

### Task 2: Database, Alembic baseline, test fixtures

The schema in `database/init/01_schema.sql` becomes Alembic revision 0001. Postgres no longer runs init scripts, so nothing can create tables behind Alembic's back.

**Files:**
- Move: `database/init/01_schema.sql` → `backend/migrations/sql/0001_baseline.sql`; repoint symlink `04-database-schema.sql` to it; delete `database/`.
- Modify: `docker-compose.yml`: remove the `./database/init` volume from `postgres`; add `command: ["sh","-c","alembic upgrade head && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"]` to `backend`.
- Create: `docker-compose.dev.yml` (override publishing `postgres` on `127.0.0.1:5433` and `valkey` on `127.0.0.1:6380` for local tests).
- Create: `backend/alembic.ini`, `backend/migrations/env.py` (async template), `backend/migrations/versions/0001_baseline.py`, `backend/migrations/versions/0002_camera_mode.py`
- Create: `backend/app/db.py`, `backend/app/models/__init__.py`, `backend/app/models/tenancy.py`, `backend/app/models/sources.py`, `backend/app/models/audit.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_schema.py`

**Interfaces:**
- Produces: `app.db.get_session() -> AsyncIterator[AsyncSession]` (FastAPI dependency); `app.db.Base` (DeclarativeBase). ORM classes mapping existing tables: `Customer`, `User`, `RefreshToken`, `Site` (in `tenancy.py`), `Camera` (in `sources.py`, including new `mode`), `AuditLog` (in `audit.py`). Map only the columns these tables have in the SQL; do not map tables later plans own.
- Produces (tests): fixtures `db_session` (AsyncSession inside an outer transaction rolled back after each test, `join_transaction_mode="create_savepoint"`), `client` (overrides `get_session` with `db_session`), `make_customer(**kw) -> Customer`, `make_user(customer, role, email=..., password="Passw0rd!long") -> User`. Tests read `TEST_DATABASE_URL`. When it is unset (local dev), conftest builds `postgresql+asyncpg://{user}:{password}@127.0.0.1:5433/visionguard_test` from `POSTGRES_USER`/`POSTGRES_PASSWORD` in the repo-root `.env` (read with `dotenv_values`; python-dotenv is a pinned dev dependency), with the password passed through `urllib.parse.quote(..., safe="")`. That way local tests use the same credentials as the dev Postgres container. CI sets `TEST_DATABASE_URL` explicitly. Tests run `alembic upgrade head` once per session.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_schema.py
async def test_baseline_tables_exist(db_session):
    names = set((await db_session.execute(text(
        "select table_name from information_schema.tables where table_schema='public'"))).scalars())
    assert {"customers","users","sites","cameras","events","rules","models",
            "model_assignments","audit_logs","alembic_version"} <= names

async def test_camera_mode_defaults_to_live_and_is_constrained(db_session, make_customer):
    c = await make_customer()
    site = Site(customer_id=c.id, name="Pitch A"); db_session.add(site); await db_session.flush()
    cam = Camera(customer_id=c.id, site_id=site.id, name="Cam", source_type="rtsp", frigate_name="cam")
    db_session.add(cam); await db_session.flush(); await db_session.refresh(cam)
    assert cam.mode == "live"
    with pytest.raises(IntegrityError):
        await db_session.execute(text(f"update cameras set mode='bogus' where id='{cam.id}'"))
```
- [ ] **Step 2: Run** `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres valkey`, create the `visionguard_test` DB, then `uv run pytest tests/test_schema.py -v` → FAIL.
- [ ] **Step 3: Implement.** Revision `0001` executes `migrations/sql/0001_baseline.sql` (downgrade drops schema `public` cascade and recreates it). Revision `0002`: `ALTER TABLE cameras ADD COLUMN mode VARCHAR(10) NOT NULL DEFAULT 'live' CHECK (mode IN ('live','upload'))` and a check that `mode='live'` implies `frigate_name IS NOT NULL`, added as `NOT VALID` then validated. ORM models and the fixtures listed above.
- [ ] **Step 4: Run tests** → PASS. Also run `uv run alembic downgrade base && uv run alembic upgrade head` against the test DB → no errors.
- [ ] **Step 5: Commit** `git commit -am "feat(db): alembic baseline from schema, camera mode, test fixtures"` (add new files first).

---

### Task 3: Problem-details errors and cursor pagination

**Files:**
- Create: `backend/app/common/__init__.py`, `backend/app/common/errors.py`, `backend/app/common/pagination.py`
- Modify: `backend/app/main.py` (register handlers)
- Test: `backend/tests/test_common.py`

**Interfaces:**
- Produces: `class ApiError(Exception): __init__(self, status: int, slug: str, title: str, detail: str | None = None, errors: list[dict] | None = None)`; helpers `not_found(entity: str) -> ApiError`, `forbidden() -> ApiError`, `conflict(detail: str) -> ApiError`. Handlers turn `ApiError`, `RequestValidationError` (slug `validation`, status 422, `errors=[{"field": <dotted loc>, "message": ...}]`) and unhandled exceptions (500, slug `internal`, no stack trace in the body) into `application/problem+json`.
- Produces: `class Page(BaseModel, Generic[T]): items: list[T]; next_cursor: str | None`; `def encode_cursor(created_at: datetime, id: UUID) -> str`; `def decode_cursor(cursor: str) -> tuple[datetime, UUID]` (raises `ApiError(400,"invalid-cursor",...)`); `async def paginate(session, stmt, model, limit: int, cursor: str | None) -> tuple[list, str | None]` ordering by `(model.created_at desc, model.id desc)`; `def limit_param(limit: int = Query(50, ge=1, le=200)) -> int`.

- [ ] **Step 1: Write failing tests**: `test_api_error_renders_problem_json` (a test route raising `not_found("site")` → 404, content-type `application/problem+json`, body `type == "https://visionguard.ai/errors/not-found"`); `test_validation_error_lists_fields`; `test_cursor_roundtrip`; `test_garbage_cursor_is_400`; `test_paginate_walks_all_rows_without_duplicates` (create 7 sites, limit 3 → pages of 3, 3, 1, then `next_cursor` None, all ids distinct).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** per the Interfaces block. The cursor is urlsafe base64 of JSON `{"t": iso8601, "id": uuid}`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(api): problem-details errors and cursor pagination`

---

### Task 4: Authentication

**Files:**
- Create: `backend/app/auth/__init__.py`, `security.py`, `service.py`, `ratelimit.py`, `deps.py`, `router.py`, `schemas.py`
- Create: `backend/app/cache.py` (Valkey client factory)
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Produces in `security.py`: `hash_password(pw: str) -> str` (argon2id); `verify_password(pw: str, hash: str) -> bool`; `create_access_token(user: User) -> str` (HS256 with `secret_key`; claims `sub`, `role`, `cid` (customer id or null), `type="access"`, `exp`); `decode_access_token(token: str) -> dict` (raises `ApiError(401,"invalid-token")`); `new_refresh_token() -> tuple[str, str]` returning (raw, sha256-hex hash).
- Produces in `deps.py`: `@dataclass CurrentUser(id: UUID, customer_id: UUID | None, role: str, email: str)`; `async def get_current_user(...) -> CurrentUser` (Bearer header; user must still exist and be active); `def require_roles(*roles: str) -> Callable` (dependency; 403 `forbidden` otherwise; `super_admin` always passes).
- Produces in `cache.py`: `get_redis() -> redis.Redis` dependency (tests override with `fakeredis.FakeRedis`).
- Produces (tests, in `conftest.py`): fixture `auth_headers(user) -> dict` returning `{"Authorization": f"Bearer {create_access_token(user)}"}`; the `client` fixture also overrides `get_redis` with a fresh `FakeRedis` per test.
- Endpoints (shapes from `05-api-specification.md` §2):
  - `POST /api/v1/auth/login` `{email, password}` → 200 `{access_token, refresh_token, token_type:"bearer", user:{id,email,full_name,role,customer_id,customer_industry}}` (`customer_industry` is null for super_admin) and a `Set-Cookie: vg_refresh=<raw>; HttpOnly; SameSite=Strict; Path=/api/v1/auth; Max-Age=604800` (`Secure` when `cookie_secure`). Unknown email, wrong password and inactive user all return the same 401 `invalid-credentials`. Updates `last_login_at`.
  - `POST /api/v1/auth/refresh`: refresh token from JSON `{refresh_token}` **or** the `vg_refresh` cookie → new pair (and a new cookie); the old token gets `revoked_at`.
  - `POST /api/v1/auth/logout` → 204, revokes the token, clears the cookie.
  - `GET /api/v1/auth/me` → user object.
- Rate limit (`ratelimit.py`): `def check_login_rate(redis, ip: str, email: str, limit: int) -> None`. Uses an INCR key `rl:login:{ip}:{lower(email)}` with a 60 s expiry; when the count exceeds `limit`, raises `ApiError(429,"rate-limited")`.

- [ ] **Step 1: Write failing tests**

```python
async def test_login_success_returns_tokens_and_httponly_cookie(client, make_customer, make_user): ...
    # assert 200, "access_token" and "refresh_token" in body, "httponly" in set-cookie lower(), "vg_refresh=" in it
async def test_login_email_is_case_insensitive(...)        # account coach@academy.rw, login Coach@Academy.rw -> 200
async def test_login_wrong_password_and_inactive_are_identical_401(...)  # same status & type for both
async def test_login_rate_limited_on_sixth_attempt_within_a_minute(...)  # 5 bad attempts -> 401 x5, 6th -> 429
async def test_refresh_rotates_token(...)                  # new refresh != old; old now revoked in DB
async def test_refresh_via_cookie(...)                     # no body, cookie only -> 200
async def test_refresh_reuse_revokes_all_user_tokens(...)  # rotate A->B, reuse A -> 401, then B -> 401 too
async def test_logout_revokes_refresh(...)                 # logout then refresh with same token -> 401
async def test_me_requires_valid_access_token(...)         # no header -> 401, valid -> 200 with role
async def test_require_roles_blocks_viewer(...)            # temp route require_roles("customer_admin"): viewer -> 403
```
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** per the Interfaces block. Look up users with `func.lower(User.email) == email.lower()`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(auth): login, rotating refresh tokens with reuse detection, rate limit`

---

### Task 5: Audit log and tenant-scoping helpers

**Files:**
- Create: `backend/app/audit/__init__.py`, `backend/app/audit/service.py`
- Create: `backend/app/tenancy/__init__.py`, `backend/app/tenancy/scoping.py`
- Modify: `backend/app/auth/router.py` (audit `auth.login`, `auth.login_failed`, `auth.logout`)
- Test: `backend/tests/test_audit.py`, `backend/tests/test_scoping.py`

**Interfaces:**
- Produces: `async def record_audit(session: AsyncSession, *, action: str, customer_id: UUID | None, actor: CurrentUser | None = None, entity_type: str | None = None, entity_id: UUID | None = None, details: dict | None = None, ip: str | None = None) -> None` (adds a row to the current transaction; it doesn't commit).
- Produces: `def scoped(stmt: Select, model, user: CurrentUser) -> Select` (adds `model.customer_id == user.customer_id` unless super_admin); `async def get_scoped_or_404(session, model, id: UUID, user: CurrentUser, entity: str) -> model`; `def resolve_customer_id(user: CurrentUser, requested: UUID | None) -> UUID` (super_admin: `requested` is required, else `ApiError(422,"validation", detail="customer_id is required")`; everyone else: always `user.customer_id`, and `requested` is ignored).

- [ ] **Step 1: Write failing tests**: `test_login_writes_audit_row` (action `auth.login`, actor id, ip); `test_failed_login_writes_audit_without_actor`; `test_audit_rows_cannot_be_updated` (raw UPDATE of `action` or `details` raises DB error containing "append-only"); `test_deleting_user_keeps_audit_row_with_null_actor` (hard-delete a user who has an audit row: the delete succeeds, and the row survives with `actor_user_id` NULL and other columns unchanged); `test_scoped_filters_other_customers`; `test_get_scoped_or_404_hides_other_customer` (raises ApiError 404); `test_resolve_customer_id_rules` (the three cases above).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: audit service and tenant scoping helpers`

---

### Task 6: Sites, users and sources (cameras) APIs

**Files:**
- Create: `backend/app/security/crypto.py`
- Create: `backend/app/sites/{__init__,schemas,router}.py`, `backend/app/users/{__init__,schemas,router}.py`, `backend/app/cameras/{__init__,schemas,router}.py`
- Modify: `backend/app/main.py` (mount routers)
- Test: `backend/tests/test_sites.py`, `test_users.py`, `test_cameras.py`, `test_crypto.py`

**Interfaces:**
- Produces: `encrypt_secret(plain: str) -> bytes`, `decrypt_secret(token: bytes) -> str` (Fernet with `credentials_encryption_key`).
- Endpoints (all paginated lists use `Page`; every write calls `record_audit` with action `<entity>.create|update|delete`):
  - Sites: `GET/POST /api/v1/sites`, `GET/PATCH/DELETE /api/v1/sites/{id}`. Create body `{name, location?, timezone="Africa/Kigali", business_hours?, customer_id?}`. Timezone validated with `zoneinfo` (bad value → 422). Writes need `customer_admin`; reads are open to any role.
  - Users: `GET/POST /api/v1/users`, `PATCH/DELETE /api/v1/users/{id}`, `customer_admin` only. Create `{email, full_name, password (min 10 chars), role in {customer_admin, operator, viewer}, telegram_chat_id?, phone?}`; `super_admin` can't be created via the API. A duplicate email ignoring case → 409. DELETE sets `is_active=false` and revokes the user's refresh tokens (rows are kept for audit FKs). Users can't deactivate themselves (409). Response never includes `password_hash`.
  - Cameras: `GET /api/v1/cameras?site_id=&mode=`, `POST`, `GET/PATCH/DELETE /api/v1/cameras/{id}`. Create `{site_id, name, mode: "live"|"upload", source_type, source_url?, frigate_name?, resolution?, fps=5}`. `mode="live"` without `frigate_name` → 422. `site_id` must belong to the caller's customer (else 404). `source_url` is encrypted into `source_url_encrypted`; responses contain `source_url_set` and never `source_url`. `customer_id` is copied from the site.

- [ ] **Step 1: Write failing tests**

```python
# test_sites.py
async def test_customer_admin_creates_and_lists_site(...)
async def test_operator_cannot_create_site(...)                       # 403
async def test_other_customers_site_is_404_for_get_patch_delete(...)  # Review Focus 3
async def test_list_never_includes_other_customers_sites(...)
async def test_super_admin_create_site_requires_customer_id(...)      # 422 (Review Focus 5)
async def test_customer_admin_customer_id_in_body_is_ignored(...)     # created under own customer
async def test_invalid_timezone_is_422(...)
async def test_site_create_is_audited(...)
# test_users.py
async def test_duplicate_email_case_insensitive_is_409(...)           # Review Focus 1
async def test_cannot_create_super_admin_via_api(...)                 # 422
async def test_delete_deactivates_and_revokes_tokens(...)             # login afterwards -> 401
async def test_cannot_deactivate_self(...)                            # 409
async def test_password_hash_never_returned(...)
# test_cameras.py
async def test_live_camera_requires_frigate_name(...)                 # 422
async def test_upload_camera_without_frigate_name_ok(...)
async def test_source_url_is_encrypted_and_never_returned(...)        # raw column != plain; get & list have source_url_set True, no "source_url" key
async def test_camera_on_other_customers_site_is_404(...)
# test_crypto.py
def test_encrypt_roundtrip_and_ciphertext_differs(): ...
```
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `uv run pytest -v` (whole suite) → PASS.
- [ ] **Step 5: Commit** `feat(api): sites, users and cameras with tenant scoping and audit`

---

### Task 7: Media storage interface and signed URLs

**Files:**
- Create: `backend/app/storage/__init__.py`, `base.py`, `local.py`, `signing.py`, `router.py`
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Produces in `base.py`: `class Storage(Protocol)` with `save(key: str, data: BinaryIO) -> int` (bytes written), `open(key: str) -> BinaryIO`, `delete(key: str) -> None` (missing key is not an error), `exists(key: str) -> bool`, `local_path(key: str) -> Path | None`; `def validate_key(key: str) -> str` (rejects empty, leading `/`, `..` segments, backslashes, NUL → `ApiError(400,"invalid-key")`); `def get_storage() -> Storage` (from settings; only `local` in V1; `s3` raises `NotImplementedError`).
- `LocalStorage(root: Path)` writes atomically (temp file + rename) and creates parent dirs.
- `signing.py`: `sign_media_url(key: str, ttl_seconds: int = 300, now: int | None = None) -> str` returns `/api/v1/media/{key}?exp=<unix>&sig=<hex>` where `sig = HMAC-SHA256(secret_key, f"{key}:{exp}")`; `verify_media_signature(key: str, exp: int, sig: str, now: int | None = None) -> bool` (constant-time compare).
- `GET /api/v1/media/{key:path}?exp=&sig=`: no auth header (the signature is the authorisation). Invalid or expired → 403 `invalid-signature`. Streams the file with a correct content type and supports HTTP Range (needed for video seeking in Plan 3).

- [ ] **Step 1: Write failing tests**: `test_local_save_open_roundtrip`; `test_delete_missing_is_noop`; `test_validate_key_rejects_traversal` (parametrised: `"../x"`, `"a/../../x"`, `"/etc/passwd"`, `"a\\b"`, `""`) (Review Focus 4); `test_signed_url_serves_file`; `test_expired_signature_403` (pass `now` past exp); `test_tampered_key_403`; `test_range_request_returns_206`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(storage): local media storage with signed, range-capable URLs`

---

### Task 8: Job queue and worker services

**Files:**
- Create: `backend/app/worker/__init__.py`, `queues.py`, `jobs.py`
- Modify: `docker-compose.yml`: `worker` command → `["rq","worker","default","--url","redis://valkey:6379/0"]`; add a `worker-sessions` service (same build/env/volumes) with command `["rq","worker","sessions","--url","redis://valkey:6379/0"]` (a single process gives concurrency 1, per spec §4).
- Test: `backend/tests/test_worker.py`

**Interfaces:**
- Produces: `QueueName = Literal["default", "sessions"]`; `def get_queue(name: QueueName, connection: redis.Redis | None = None) -> rq.Queue`; `def ping(message: str) -> str` in `jobs.py` (returns `f"pong:{message}"`; smoke-test job). Later plans add jobs to `jobs.py`-adjacent modules and enqueue via `get_queue`.

- [ ] **Step 1: Write failing tests**: `test_ping_job_runs_on_default_queue` (FakeRedis connection, enqueue `ping("x")`, `SimpleWorker([q], connection=...).work(burst=True)`, `job.result == "pong:x"`); `test_sessions_queue_is_separate` (a job on `sessions` is not processed by a worker listening only on `default`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(worker): rq queues with separate sessions worker`

---

### Task 9: Bootstrap CLI

There's no self-registration, so the first accounts come from a CLI.

**Files:**
- Create: `backend/app/cli.py`
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Produces: `python -m app.cli create-super-admin --email E --name N` (prompts for a password twice, or reads `VG_PASSWORD` for non-interactive use), and `python -m app.cli create-customer --name N --industry sports|restaurant|retail|factory|school|security|other --admin-email E --admin-name N` (creates the customer and its first `customer_admin`; prints the customer id). Both are idempotent on email: an existing email exits with code 1 and a message, without changing anything. Both write audit rows (`cli.create_super_admin`, `cli.create_customer`).
- Internals exposed for tests: `async def create_super_admin(session, email, name, password) -> User`; `async def create_customer_with_admin(session, name, industry, admin_email, admin_name, password) -> tuple[Customer, User]`.

- [ ] **Step 1: Write failing tests**: `test_create_customer_with_admin_then_admin_can_login`; `test_duplicate_admin_email_raises_without_side_effects`; `test_super_admin_has_null_customer`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (argparse; `asyncio.run`). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(cli): bootstrap super admin and customer`

---

### Task 10: Dashboard scaffold: tokens, layout shell, auth

**Files:**
- Create: `dashboard/package.json` (pinned: `react@18.3.1`, `react-dom@18.3.1`, `react-router-dom@6.28.0`, `vite@5.4.11`, `typescript@5.6.3`, `vitest@2.1.5`, `@testing-library/react@16.0.1`, `@testing-library/user-event@14.5.2`, `msw@2.6.4`, `@fontsource/inter@5.1.0`, `jsdom@25.0.1`), `vite.config.ts` (dev proxy `/api` → `http://localhost:8100`), `tsconfig.json`, `index.html`
- Create: `dashboard/src/main.tsx`, `src/theme/tokens.css` (Global Constraints tokens verbatim plus base styles; body background `var(--bg-page)`; tabular numerals utility class `.num`), `src/theme/global.css`
- Create: `dashboard/src/api/client.ts`, `src/auth/AuthContext.tsx`, `src/auth/LoginPage.tsx`, `src/auth/RequireAuth.tsx`
- Create: `dashboard/src/layout/AppShell.tsx`, `Sidebar.tsx`, `TopBar.tsx`, `src/layout/nav.ts`
- Create: `dashboard/src/pages/{LiveOperations,FaultCenter,Sessions,Cameras,Settings,NotFound}.tsx` (each shows the empty state copy from UI doc §8 where one exists)
- Test: `dashboard/src/test/setup.ts`, `src/test/server.ts` (MSW), `src/auth/auth.test.tsx`, `src/layout/shell.test.tsx`, `src/api/client.test.ts`

**Interfaces:**
- Consumes: Task 4 endpoints (`/api/v1/auth/login|refresh|logout|me`).
- Produces: `apiFetch<T>(path: string, init?: RequestInit): Promise<T>` in `client.ts`. It sends `credentials: "include"` and `Authorization: Bearer <access>` from memory. On a 401 it calls `/api/v1/auth/refresh` **once** (cookie-based; concurrent 401s share one in-flight refresh), then retries. If the refresh fails, it calls the `onUnauthenticated` callback. It throws `ApiProblem` (`{status, type, title, detail}`) for problem responses. **The refresh token is never stored in JS**; only the httpOnly cookie holds it.
- Produces: `useAuth(): { user: User | null; login(email, password): Promise<void>; logout(): Promise<void>; status: "loading"|"authenticated"|"anonymous" }`. On load it tries a silent refresh to restore the session.
- Produces: `NAV_ITEMS` in `nav.ts`: `[{path:"/live", label:"Live Operations"}, {path:"/faults", label:"Fault Center"}, {path:"/sessions", label:"Sessions"}, {path:"/cameras", label:"Cameras & Screens"}, {path:"/settings", label:"Settings"}]`. The default route `/` redirects to `/sessions` for `industry==="sports"` customers and `/live` otherwise (from `user.customer_industry` in `/auth/me`).
- Layout per UI doc §4 and §10: slim fixed sidebar (≥1024 px full, 768–1023 px icon-only, <768 px bottom navigation), top bar with site name placeholder, date badge and user menu. The selected nav item uses a coral left indicator and a `--brand-soft` background. Focus rings are visible, touch targets ≥44 px, and `prefers-reduced-motion` is respected.

- [ ] **Step 1: Write failing tests**

```tsx
test("unauthenticated user is redirected to /login")
test("successful login shows the app shell with all five nav items")
test("wrong password shows the problem detail message and stays on /login")
test("operator sees 'Coach' label in user menu when customer industry is sports")
test("active nav item has aria-current='page'")
// client.test.ts
test("401 triggers exactly one refresh for two concurrent requests, then both retry")
test("failed refresh calls onUnauthenticated")
test("problem+json errors are thrown as ApiProblem with type and detail")
```
- [ ] **Step 2: Run** `cd dashboard && npm install && npx vitest run` → FAIL.
- [ ] **Step 3: Implement** per the Interfaces block.
- [ ] **Step 4: Run** `npx vitest run && npx tsc --noEmit && npx vite build` → all pass, build succeeds.
- [ ] **Step 5: Commit** `feat(dashboard): React shell with design tokens, routing and cookie-based auth`

---

### Task 11: Dashboard container and full-stack smoke test

**Files:**
- Create: `dashboard/Dockerfile` (multi-stage: `node:20.18.0-alpine` build → `nginx:1.27.2-alpine`), `dashboard/nginx.conf` (listens on **8501**; serves the SPA with `try_files $uri /index.html`; `location /api/ { proxy_pass http://backend:8000; }` with WebSocket upgrade headers for Plan 3/4; `client_max_body_size 0` and `proxy_request_buffering off` for resumable uploads in Plan 2; security headers `X-Content-Type-Options nosniff`, `Referrer-Policy same-origin`, `X-Frame-Options DENY`)
- Modify: `docker-compose.yml`: `dashboard` healthcheck `wget -qO- http://localhost:8501/ >/dev/null`
- Create: `scripts/smoke.sh`

**Interfaces:**
- Consumes: everything above.
- Produces: `scripts/smoke.sh`, which builds and starts the core services, runs `create-customer` through `docker compose exec backend python -m app.cli`, logs in through `http://127.0.0.1:8501/api/v1/auth/login` (via nginx), creates a site, and exits non-zero on any failure.

- [ ] **Step 1: Write** `scripts/smoke.sh` (bash, `set -euo pipefail`, uses `curl` + `python3 -c` for JSON) with the assertions above.
- [ ] **Step 2: Run** `./scripts/smoke.sh` → FAIL (dashboard image doesn't exist yet).
- [ ] **Step 3: Implement** the Dockerfile and nginx config.
- [ ] **Step 4: Run** `./scripts/smoke.sh` → prints `SMOKE OK`. Also open `http://localhost:8501` in a browser, log in, and confirm the shell renders with the warm-gray background and coral active nav.
- [ ] **Step 5: Commit** `feat(deploy): dashboard container behind nginx, full-stack smoke test`

---

### Task 12: Continuous integration

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Jobs:
  - `backend`: ubuntu-24.04; services `postgres:16.4-alpine` (env DB `visionguard_test`, user/password `visionguard`, port 5433:5432) and `valkey/valkey:8.0.1-alpine`; env `TEST_DATABASE_URL=postgresql+asyncpg://visionguard:visionguard@127.0.0.1:5433/visionguard_test`; `astral-sh/setup-uv`; `uv run pytest -q`.
  - `dashboard`: node 20.18.0; `npm ci`; `npx vitest run`; `npx tsc --noEmit`; `npx vite build`.
  - `compose`: `docker compose config -q` with a dummy `.env` generated from `.env.example`.
  - `licenses`: fails if `pip-licenses` (backend) or `license-checker --onlyAllow "MIT;BSD;Apache-2.0;ISC;0BSD;BSD-2-Clause;BSD-3-Clause;Python-2.0;MPL-2.0"` (dashboard) finds anything else, or if any installed package name matches `ultralytics`.

- [ ] **Step 1: Write** the workflow.
- [ ] **Step 2: Verify locally** that each job's commands pass (`uv run pytest -q`, the dashboard commands, `docker compose config -q`, and both license checks). The workflow lives at the repo root (`.github/workflows/ci.yml`) and runs on push to `origin` (github.com/IshChristian/faults-detector).
- [ ] **Step 3: Commit** `ci: backend, dashboard, compose and license checks`

---

### Task 13: M0 benchmark spike (go/no-go for upload mode)

A throwaway spike, so no TDD. Its output is a decision, not product code. It lives in `spikes/` and is never imported by `backend/`.

**Files:**
- Create: `spikes/m0-benchmark/pyproject.toml` (`rfdetr`, `supervision`, `opencv-python`, `numpy`; Python 3.11)
- Create: `spikes/m0-benchmark/run.py`
- Create: `spikes/m0-benchmark/RESULTS.md`

**Interfaces:**
- `run.py --video PATH --sample-fps 10 --seconds 300 [--tile-far-half] [--out DIR]`:
  - Reads frames at `sample-fps` and runs RF-DETR Nano (COCO weights) for `person` and `sports ball` (confidence 0.3), then ByteTrack (`supervision`).
  - With `--tile-far-half`, also runs detection on the top half of the frame upscaled 2×, and merges with NMS (IoU 0.5).
  - Writes `out/metrics.json` (`ms_per_frame_mean`, `ms_per_frame_p95`, `persons_per_frame` histogram, `tracks_total`, `track_length_median_s`, `ball_detected_frame_ratio`), `out/annotated.mp4` (first 60 s, boxes + track IDs) and `out/frames/` (10 evenly spaced annotated frames for hand-checking).

- [ ] **Step 1: Run without tiling** on the Task 0 clip: `uv run python run.py --video ~/vg-footage/test-session.mp4 --out out/plain`.
- [ ] **Step 2: Run with tiling:** `... --tile-far-half --out out/tiled`.
- [ ] **Step 3: Hand-check** the 10 frames from each run: count on-pitch players visible vs detected.
- [ ] **Step 4: Write `RESULTS.md`** answering, with numbers:
  - Projected processing time for 90 min at 10 fps on this laptop, and estimated on the N100 pilot box (laptop time × 0.6; note the assumption).
  - Hand-checked detection rate against the spec target (≥ 85% of on-pitch players in ≥ 80% of frames).
  - Whether tiling is needed, and its cost.
  - Ball detection ratio (informational).
  - **Verdict:** GO, GO-with-tiling, or NO-GO, with the recommended sample fps for Plan 2.
- [ ] **Step 5: Commit** `spike: M0 detection/tracking benchmark and go/no-go` (`out/` is git-ignored; add `spikes/**/out/` to `.gitignore`).

**If the verdict is NO-GO:** stop and bring `RESULTS.md` to the owner before writing Plan 2. Options are a higher camera position, the RF-DETR Small model, or a lower sample fps; it's their call.

---

## Definition of done (Plan 1)
- `uv run pytest` and `npx vitest run` are green; `./scripts/smoke.sh` prints `SMOKE OK`.
- A customer admin can log in at `http://localhost:8501`, and through the API can create sites, users and cameras (both modes) with tenant isolation and an audit trail.
- `spikes/m0-benchmark/RESULTS.md` has a verdict.

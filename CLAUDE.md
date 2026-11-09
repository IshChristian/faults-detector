# VisionGuard AI (ONEVISION)

A self-hosted video analytics platform with two modes. **Upload mode** analyses football-academy training videos. **Live mode** turns CCTV detections from Frigate into rules, incidents and alerts.

**This repo (`~/dev/ONEVISION`, branch `plan-1-foundation`, remote `IshChristian/faults-detector`) is the canonical copy.** An older duplicate on the USB drive `/media/ishimchristian/dev/START/ONEVISION` is abandoned: the drive failed and went read-only on 2026-11-09. A backup of it is in `~/vg-backup-2026-11-09/`. Don't work there.

## Where things are

- `docs/superpowers/specs/2026-11-07-visionguard-v1-design.md` is the V1 spec. **Where it disagrees with the numbered docs (00–16), the spec wins.**
- `docs/superpowers/plans/` holds the implementation plans (Plan 1 = foundation; Plans 2–5 come later).
- `backend/` is FastAPI + async SQLAlchemy 2 + Alembic (Python 3.11, uv). `dashboard/` is React + Vite + TypeScript. `scripts/` has `smoke.sh` and the licence checker. `spikes/m0-benchmark/` is the M0 detection benchmark.
- `05-api-specification.md` gives the API conventions. `16-ui-ux-design-document.pdf` gives the UI tokens and layout.

## Progress and resuming

- The executor ledger for Plan 1 is `.superpowers/sdd/2026-11-07-plan-1-foundation/progress.md` (git-ignored). It records every task's completion line and every `Ruling:`. Read it before resuming. A task is done only if it has a `complete` line **and** its commit is in `git log`.
- Execute plans with `superpowers:executing-plans`, test-first (TDD), one commit per task, and append a ledger line after each task.
- Plan 1 status: Tasks 1–12 and the final self-review are done. Still open:
  - Task 11: `bash scripts/smoke.sh` must print `SMOKE OK`, followed by a browser check at http://localhost:8501.
  - Task 13: needs the owner's 5-minute clip at `~/vg-footage/test-session.mp4` and about 2 GB of free disk.
  - Review items 7 (uvicorn `--proxy-headers`) and 8 (the Secure cookie over plain-HTTP LAN) need an owner decision.

## Commands

```bash
# Test DB + cache for the backend suite (Postgres on 127.0.0.1:5433, Valkey on 6380)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres valkey
docker compose exec postgres createdb -U "$POSTGRES_USER" visionguard_test   # first time only

cd backend && uv run pytest -q
cd dashboard && npx vitest run && npx tsc --noEmit && npx vite build
bash scripts/smoke.sh          # full stack through nginx; prints SMOKE OK
```

The home disk is nearly full (about 3 GB free). Prune Docker build cache (`docker builder prune`) when images pile up, and don't install large ML wheels outside the spike.

## Rules that must hold

- Python 3.11. Shipped dependencies must be MIT/BSD/Apache-2.0 (checked in CI). **No Ultralytics anywhere.** Pin versions exactly, and never use `latest` image tags.
- Roles are exactly `super_admin`, `customer_admin`, `operator`, `viewer`. The UI shows "Coach" for operator when the customer's industry is sports.
- Every customer-owned query is scoped by `customer_id`. Another tenant's resource returns **404**, never 403.
- Errors are RFC 9457 `application/problem+json`. Lists use cursor pagination (`{items, next_cursor}`).
- Writes record an audit row (`audit_logs` is append-only). Camera `source_url` is Fernet-encrypted and never returned.
- Alembic owns the schema; nothing else creates tables. Host ports: API 8100, dashboard 8501. Port 8000 is reserved for Coolify.
- The refresh token lives only in the httpOnly `vg_refresh` cookie, never in JS.
- **Secrets live only in `.env` (git-ignored).** Never put real credentials in `.env.example` or any tracked file.
- End commit messages with the `Co-Authored-By` attribution line. Don't push or merge without the owner's say-so.

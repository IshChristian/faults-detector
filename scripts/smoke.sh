#!/usr/bin/env bash
# Full-stack smoke test: build and start the core app services, create a customer through
# the CLI, log in through nginx (the dashboard port), create a site. Prints SMOKE OK.
#
# Frigate and Mosquitto are not needed for this check and are not started here.
# Each run creates a uniquely named "Smoke ..." customer; that data stays in the database.
set -euo pipefail

cd "$(dirname "$0")/.."
[[ -f .env ]] || { echo "Missing .env (copy .env.example)"; exit 1; }
set -a; . ./.env; set +a

BASE="http://127.0.0.1:${DASHBOARD_PORT:-8501}"
STAMP="$(date +%s)"
EMAIL="smoke-${STAMP}@example.com"
PASSWORD="smoke-password-${STAMP}"
SERVICES=(postgres valkey backend worker worker-sessions dashboard)

fail() { echo "SMOKE FAILED: $*" >&2; exit 1; }
json() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }

echo "==> Building and starting: ${SERVICES[*]}"
docker compose up -d --build --no-deps "${SERVICES[@]}"

echo "==> Waiting for the dashboard and API (up to 3 minutes)"
for _ in $(seq 1 90); do
  if curl -fsS "$BASE/" >/dev/null 2>&1 && curl -fsS "$BASE/api/v1/health" >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 2
done
[[ "${ready:-0}" == 1 ]] || { docker compose ps; fail "stack did not become healthy"; }

echo "==> Creating customer via the CLI"
CUSTOMER_ID="$(docker compose exec -T -e VG_PASSWORD="$PASSWORD" backend \
  python -m app.cli create-customer --name "Smoke ${STAMP}" --industry other \
  --admin-email "$EMAIL" --admin-name "Smoke Admin" | tail -n1 | tr -d '\r')"
[[ "$CUSTOMER_ID" =~ ^[0-9a-f-]{36}$ ]] || fail "unexpected CLI output: $CUSTOMER_ID"

echo "==> Logging in through nginx"
LOGIN="$(curl -fsS -X POST "$BASE/api/v1/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")" || fail "login request failed"
TOKEN="$(echo "$LOGIN" | json '["access_token"]')"
[[ "$(echo "$LOGIN" | json '["user"]["customer_id"]')" == "$CUSTOMER_ID" ]] || fail "login returned the wrong customer"

echo "==> Creating a site"
STATUS="$(curl -sS -o /tmp/vg-smoke-site.json -w '%{http_code}' -X POST "$BASE/api/v1/sites" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name":"Smoke site"}')"
[[ "$STATUS" == 201 ]] || fail "create site returned HTTP $STATUS: $(cat /tmp/vg-smoke-site.json)"

echo "SMOKE OK"

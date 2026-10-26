#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
# .env is protected operator-owned shell-compatible KEY=VALUE data; never commit it.
set -a; source .env; set +a
: "${DATA_ROOT:?}" "${TLS_ROOT:?}" "${ALLOWED_ORIGINS:?}"
[[ "$APP_ENV" == production ]] || { echo 'APP_ENV must be production'; exit 1; }
[[ "$POSTGRES_PASSWORD" != *replace* && "$APP_DB_PASSWORD" != *replace* && "$REDIS_PASSWORD" != *replace* ]] || { echo 'Replace example passwords'; exit 1; }
mountpoint -q "$DATA_ROOT" || { echo 'DATA_ROOT must be a dedicated encrypted EBS mount'; exit 1; }
test -r "$TLS_ROOT/fullchain.pem" && test -r "$TLS_ROOT/privkey.pem"
# EC2 EBS encryption must be verified through AWS, not inferred from mountpoint.
compose=(docker compose -f compose.yaml -f infra/compose.production.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" build
# Run migrations before new API/worker processes. Existing deployments require backup first.
"${compose[@]}" up -d db redis
"${compose[@]}" run --rm migrate
"${compose[@]}" up -d --wait
bash tools/smoke.sh "${ALLOWED_ORIGINS%%,*}"

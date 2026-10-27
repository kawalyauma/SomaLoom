#!/usr/bin/env bash
# Creates and removes ONLY disposable containers belonging to this invocation.
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin=${PYTHON:-.venv/bin/python}
log_root=${VERIFY_LOG_ROOT:-verification/native}
mkdir -p "$log_root"
suffix="$(date +%s)-$RANDOM"
db_name="somaloom-qa-db-$suffix"
redis_name="somaloom-qa-redis-$suffix"
cleanup() { docker rm -f "$db_name" "$redis_name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
password=$("$python_bin" -c 'import secrets; print(secrets.token_hex(24))')
docker run -d --name "$db_name" --memory=384m -e POSTGRES_USER=test -e POSTGRES_PASSWORD="$password" -e POSTGRES_DB=somaloom_test -p 127.0.0.1::5432 pgvector/pgvector:pg16 >/dev/null
docker run -d --name "$redis_name" --memory=96m -p 127.0.0.1::6379 redis:7-alpine >/dev/null
for attempt in $(seq 1 60); do
  if docker exec "$db_name" pg_isready -U test -d somaloom_test >/dev/null 2>&1; then break; fi
  sleep 1
done
db_port=$(docker port "$db_name" 5432/tcp | cut -d: -f2)
redis_port=$(docker port "$redis_name" 6379/tcp | cut -d: -f2)
export APP_ENV=test
export DATABASE_URL="postgresql+psycopg://test:$password@127.0.0.1:$db_port/somaloom_test"
export TEST_DATABASE_URL="$DATABASE_URL"
export TEST_REDIS_URL="redis://127.0.0.1:$redis_port/15"
"$python_bin" -m alembic upgrade head 2>&1 | tee "$log_root/migration-upgrade.log"
"$python_bin" -m alembic check 2>&1 | tee "$log_root/schema-drift.log"
"$python_bin" -m pytest -q 2>&1 | tee "$log_root/pytest.log"
"$python_bin" tools/migration_drill.py 2>&1 | tee "$log_root/migration-drill.log"
echo 'Native verification passed; real AI, Telegram, authorized-site and cloud restore remain separate gates.'

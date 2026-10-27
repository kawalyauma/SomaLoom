#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin=${PYTHON:-.venv/bin/python}
log_root=${VERIFY_LOG_ROOT:-verification/local}
mkdir -p "$log_root"
run() { local name=$1; shift; "$@" 2>&1 | tee "$log_root/$name.log"; }
run lint "$python_bin" -m ruff check .
run format "$python_bin" -m ruff format --check .
run compile "$python_bin" -m compileall -q apps/api services contracts db
run pytest "$python_bin" -m pytest -q
run typecheck npm --prefix apps/web run typecheck
run web-build env NEXT_TELEMETRY_DISABLED=1 npm --prefix apps/web run build
run npm-audit npm --prefix apps/web audit --omit=dev --audit-level=high
echo 'Local verification passed. Native PostgreSQL/Redis and external-service gates are separate.'

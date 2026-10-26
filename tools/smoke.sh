#!/bin/bash
set -euo pipefail
base="${1:-http://localhost:8000}"
curl --fail --silent --show-error "$base/api/v1/health" | python3 -c 'import sys,json; assert json.load(sys.stdin)["status"] == "ok"'
curl --fail --silent --show-error "$base/api/v1/ready" | python3 -c 'import sys,json; assert json.load(sys.stdin)["status"] == "ready"'
curl --fail --silent --show-error "$base/api/v1/openapi.json" | python3 -c 'import sys,json; assert "/api/v1/users/me" in json.load(sys.stdin)["paths"]'
code=$(curl --silent --output /dev/null --write-out '%{http_code}' "$base/api/v1/users/me")
[[ "$code" == 401 ]]
echo 'Health, readiness, OpenAPI and unauthenticated denial checks passed'

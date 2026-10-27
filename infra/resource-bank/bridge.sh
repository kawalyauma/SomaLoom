#!/bin/sh
set -eu
cd /opt/somaloom
bank_path=$(python3 - <<'PYROOT'
from pathlib import Path
values=dict(line.split('=',1) for line in Path('.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
print(values['DATA_ROOT'].strip('"\'')+'/resources/resource-bank')
PYROOT
)
mkdir -p "$bank_path/outbox" "$bank_path/receipts" "$bank_path/results" "$bank_path/status"
chown -R 10001:10001 "$bank_path"
docker exec somaloom-api-1 python -m services.resource_bank.exchange export
if [ -s "$bank_path/.github-token" ]; then
 # This short-lived trusted sync process sees only selected reference packets and the repository token.
 # It has no app DB, Codex credential or AWS account credential.
 docker run --rm --user 10001:10001 -v "$bank_path:/data/resources/resource-bank" somaloom-api python tools/sync_resource_bank.py
fi
docker exec somaloom-api-1 python -m services.resource_bank.exchange ingest

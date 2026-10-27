#!/bin/bash
# DESTRUCTIVE: use an isolated recovery host and verify before changing production DNS.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
[[ "${1:-}" == --replace-database-and-resources && -n "${2:-}" ]] || { echo 'Usage: tools/restore.sh --replace-database-and-resources BACKUP_ID'; exit 1; }
backup_id="$2"
[[ "$backup_id" =~ ^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$ ]] || { echo 'Invalid backup ID'; exit 1; }
set -a; source .env; set +a
: "${DATA_ROOT:?}" "${BACKUP_BUCKET:?}"
compose=(docker compose -f compose.yaml -f infra/compose.production.yaml)
staging=$(mktemp -d "$DATA_ROOT/restore.XXXXXXXX")
trap 'rm -rf "$staging"' EXIT
for file in database.sql resources.tar.gz SHA256SUMS; do
  aws s3 cp "s3://$BACKUP_BUCKET/somaloom/$backup_id/$file" "$staging/$file" --only-show-errors
done
(cd "$staging" && sha256sum --check SHA256SUMS)
mkdir "$staging/resources"
python3 - "$staging" <<'PYTHON'
import pathlib, sys, tarfile
root = pathlib.Path(sys.argv[1])
with tarfile.open(root / "resources.tar.gz") as archive:
    archive.extractall(root / "resources", filter="data")
PYTHON
"${compose[@]}" stop nginx web api worker dispatcher
"${compose[@]}" exec -T db sh -c 'psql -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" "$POSTGRES_DB"' < "$staging/database.sql"
# Preserve the previous resource tree for operator recovery instead of deleting it.
previous="$DATA_ROOT/resources.before-restore.$(date -u +%Y%m%dT%H%M%SZ)"
mv "$DATA_ROOT/resources" "$previous"
mv "$staging/resources" "$DATA_ROOT/resources"
chown -R 10001:10001 "$DATA_ROOT/resources"
"${compose[@]}" run --rm migrate
"${compose[@]}" up -d --wait
bash tools/smoke.sh "${ALLOWED_ORIGINS%%,*}"
echo 'Restore smoke checks passed; verify sample documents, accounts and feature jobs before promotion.'

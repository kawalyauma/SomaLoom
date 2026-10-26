#!/bin/bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
set -a; source .env; set +a
: "${DATA_ROOT:?}" "${BACKUP_BUCKET:?}" "${BACKUP_KMS_KEY_ID:?}"
compose=(docker compose -f compose.yaml -f infra/compose.production.yaml)
# Keep staging files on the encrypted data volume. Immutable object versions plus paused
# writers ensure SQL references and resource files describe the same checkpoint.
staging=$(mktemp -d "$DATA_ROOT/backup.XXXXXXXX")
paused=false
cleanup() { if $paused; then "${compose[@]}" unpause api worker >/dev/null; fi; rm -rf "$staging"; }
trap cleanup EXIT
paused=true
"${compose[@]}" pause api worker
"${compose[@]}" exec -T db sh -c 'pg_dump --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$staging/database.sql"
tar -C "$DATA_ROOT/resources" -czf "$staging/resources.tar.gz" .
"${compose[@]}" unpause api worker
paused=false
(cd "$staging" && sha256sum database.sql resources.tar.gz > SHA256SUMS)
backup_id=$(date -u +%Y%m%dT%H%M%SZ)-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')
# IAM role, bucket versioning, block-public-access and retention are operator prerequisites.
for file in database.sql resources.tar.gz SHA256SUMS; do
  aws s3 cp "$staging/$file" "s3://$BACKUP_BUCKET/somaloom/$backup_id/$file" --sse aws:kms --sse-kms-key-id "$BACKUP_KMS_KEY_ID" --only-show-errors
done
echo "Backup uploaded: somaloom/$backup_id (restore verification still required)"

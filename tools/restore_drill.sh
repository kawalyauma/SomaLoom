#!/usr/bin/env bash
# Restore an off-instance backup into NEW disposable containers/directories only.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
backup_id=${1:?Backup ID required}
[[ "$backup_id" =~ ^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$ ]] || exit 2
set -a; source .env; set +a
: "${DATA_ROOT:?}" "${BACKUP_BUCKET:?}"
staging=$(mktemp -d "$DATA_ROOT/restore-drill.XXXXXXXX")
container="somaloom-restore-drill-$RANDOM"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; rm -rf "$staging"; }
trap cleanup EXIT
for file in database.sql resources.tar.gz SHA256SUMS; do
  aws s3 cp "s3://$BACKUP_BUCKET/somaloom/$backup_id/$file" "$staging/$file" --only-show-errors
done
(cd "$staging" && sha256sum --check SHA256SUMS)
mkdir "$staging/resources"
python3 - "$staging" <<'PY'
import pathlib,sys,tarfile
root=pathlib.Path(sys.argv[1])
with tarfile.open(root/'resources.tar.gz') as archive:
    archive.extractall(root/'resources',filter='data')
PY
password=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
docker run -d --name "$container" --memory=512m -e POSTGRES_USER=restore -e POSTGRES_DB=restore_drill -e POSTGRES_PASSWORD="$password" pgvector/pgvector:pg16 >/dev/null
for attempt in $(seq 1 60); do
  if docker exec "$container" pg_isready -U restore -d restore_drill >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec -i "$container" psql -q -v ON_ERROR_STOP=1 --single-transaction -U restore -d restore_drill < "$staging/database.sql" > "$staging/restore.log" 2>&1
tables=$(docker exec "$container" psql -At -U restore -d restore_drill -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
users=$(docker exec "$container" psql -At -U restore -d restore_drill -c 'SELECT count(*) FROM users')
versions=$(docker exec "$container" psql -At -U restore -d restore_drill -c 'SELECT count(*) FROM resource_versions')
[[ "$tables" -ge 35 && "$users" -ge 2 ]]
# Compare every immutable object key/checksum referenced by the restored database.
docker exec "$container" psql -At -F '|' -U restore -d restore_drill -c 'SELECT tenant_id,object_key,checksum_sha256 FROM resource_versions' > "$staging/objects.txt"
python3 - "$staging" <<'PY'
import hashlib,pathlib,sys
root=pathlib.Path(sys.argv[1]);verified=0
for line in (root/'objects.txt').read_text().splitlines():
    tenant,key,checksum=line.split('|')
    obj=(root/'resources'/tenant/key).resolve()
    assert obj.is_relative_to((root/'resources').resolve())
    assert hashlib.sha256(obj.read_bytes()).hexdigest()==checksum
    verified+=1
print(f'PASS: restored {verified} referenced originals match SHA-256')
PY
docker exec "$container" psql -At -F '|' -U restore -d restore_drill -c "SELECT tenant_id,object_key,format FROM exports WHERE object_key IS NOT NULL" > "$staging/exports.txt"
python3 - "$staging" <<'PYEXPORT'
import pathlib,sys,zipfile
root=pathlib.Path(sys.argv[1]);verified=0
for line in (root/'exports.txt').read_text().splitlines():
    tenant,key,fmt=line.split('|')
    obj=(root/'resources'/tenant/key).resolve()
    assert obj.is_relative_to((root/'resources').resolve()) and obj.stat().st_size>1000
    if fmt=='pdf': assert obj.read_bytes().startswith(b'%PDF-')
    elif fmt=='docx':
        with zipfile.ZipFile(obj) as archive: assert 'word/document.xml' in archive.namelist()
    else: raise AssertionError('Unexpected export format')
    verified+=1
print(f'PASS: restored {verified} published PDF/DOCX files retain valid structures')
PYEXPORT
echo "PASS: off-instance restore into disposable PostgreSQL: tables=$tables users=$users resource_versions=$versions; live deployment unchanged"

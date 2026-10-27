# Encrypted backup and restore

Production deletion or replacement always requires owner approval and a verified restore path. Do not run tools/restore.sh against production merely because this runbook exists.

## Backup

`bash tools/backup.sh` pauses API, worker and dispatcher writers, snapshots PostgreSQL with pg_dump and the durable resource tree, resumes writers, creates SHA256SUMS and uploads database.sql/resources.tar.gz/SHA256SUMS to a unique private S3 prefix using KMS encryption. Secrets are read from the protected operator-owned .env; no values are printed. Bucket versioning, public-access blocking, TLS-only policy and IAM/KMS restrictions are required. If S3 is selected for primary object storage, separately verify/version/restore that object prefix; this EBS snapshot script is not an S3 object-store backup.

The systemd daily timer runs at 02:00 UTC with a small randomized delay. Writers include the unified dispatcher; omitting it could create new references during the snapshot. The script's cleanup trap resumes paused writers on failure.

## Disposable restore drill

```bash
bash tools/restore_drill.sh BACKUP_ID
```

Run on the staging/administration host with backup access. This downloads the ACTUAL off-instance objects, verifies SHA256SUMS, safely extracts the resource archive, restores PostgreSQL into a NEW uniquely named disposable pgvector container, checks the table/user counts, and verifies the SHA-256 of every original resource referenced by the restored database. It removes only its own disposable container/directory. The live database and resources are not replaced.

Record the backup ID, counts, object checksums, image version and drill result. A successful upload is not a successful restore. Real-data retention/RPO/RTO and alert delivery need owner agreement; no real student or textbook materials belong in the evidence log.

## Recovery/promotion

`tools/restore.sh --replace-database-and-resources BACKUP_ID` is destructive to its target database. It verifies archive checksums, stops web/API/worker/dispatcher writers, restores SQL, preserves the previous resource tree, installs recovered files and performs migration/smoke checks. Use only on a separately provisioned recovery host after approval for any production replacement. Verify accounts, sessions, tenant isolation, originals, generated versions, exports, pending jobs and source permissions before routing traffic. Do not promote on an HTTP health response alone.

Feature downgrades intentionally drop feature tables. Prefer a compatible application rollback or roll-forward; use a verified recovery environment for incompatible schema rollback. Keep last-known-good code/image/archive and data checkpoints paired.

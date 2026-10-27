# EC2 deployment and recovery

## Prerequisites and launch gate

No EC2 deployment is claimed by repository configuration. Obtain an Ubuntu 24.04 EC2 instance (start with 4 vCPU / 8 GiB; extraction capacity requires measurement), DNS A record, an encrypted dedicated EBS data volume mounted at `/srv/somaloom-data`, a private versioned S3 backup bucket with public access blocked, and a KMS key. Use instance IAM credentials, no access keys in files. Allow inbound TCP 80/443; use Session Manager, or restrict SSH to an operator IP. Database/Redis have no published ports. API and web bind host loopback for local checks. Restrict EC2 metadata to IMDSv2; do not give untrusted feature code access to the instance role.

Runtime instance IAM: only required backup prefix PutObject/GetObject/ListBucket (prefix scoped), and KMS GenerateDataKey/Decrypt for that key. Separate restore access if operators need different permissions. Require TLS and SSE-KMS in bucket policy. Enable versioning and lifecycle retention (suggest 30 daily copies). EBS snapshots and database dumps are separate safeguards.

## Provision and start

1. Use `infra/ec2/cloud-init.yaml` or provision Docker Compose v2, AWS CLI v2, Python 3.12, curl and certbot manually. Verify cloud-init package availability on the selected AMI. Clone into `/opt/somaloom`; deploy a reviewed commit SHA.
2. Verify EBS encryption with `aws ec2 describe-volumes` and mount the data filesystem using its UUID in `/etc/fstab`. Create postgres/redis/resources directories. Resource owner is uid/gid 10001; database and Redis ownership is initialized by their official images. Confirm no accidental root-filesystem data directory when the mount is absent.
3. Copy `.env.production.example` to `.env`, chmod 600. Generate independent 64-hex-character owner/app/Redis passwords (`openssl rand -hex 32`). Keep DATABASE_URL and REDIS_URL consistent for host tooling; Compose supplies container URLs. Password characters in URLs must be percent-encoded; generated hex avoids ambiguity. Never print `docker compose config` with interpolated secrets; use `--quiet`.
4. Obtain a public certificate using certbot standalone on port 80 before Nginx starts, or DNS validation. Copy `fullchain.pem` and `privkey.pem` into TLS_ROOT with permissions readable by Nginx uid 101 only. Mount the entire directory so atomic certificate renewals are visible. Configure a renewal timer and deploy hook to copy files and run `docker compose -f compose.yaml -f infra/compose.production.yaml exec nginx nginx -s reload`. Verify externally after renewal. Do not use self-signed certificates for launch.
5. Run `sudo bash tools/deploy.sh`. The script checks the dedicated mount, builds images, runs migrations as owner, grants only application DML, then waits for services and performs external HTTPS health checks. Run `docker compose exec api python tools/provision_admin.py` interactively to provision the first administrator. The app role cannot change DDL or update/delete audit logs. School admins can provision teacher/reviewer users only in their school; platform admins provision schools/admins.
6. Sign in through HTTPS, verify Secure/HttpOnly/SameSite cookie attributes, create two schools, confirm cross-school denial and run feature end-to-end checks after integration. Confirm DB/Redis are unreachable publicly. Record commit, certificate expiry, volume encryption and backup restore evidence in `docs/VERIFICATION.md`.

For first-time development: `python3 tools/init_dev_env.py && docker compose up --build -d --wait`. Provision admin with `docker compose exec api python tools/provision_admin.py`. Stop using `docker compose down`; `down -v` destroys development data.

## Backups and restore

Install `infra/systemd/somaloom-backup.{service,timer}` into `/etc/systemd/system`, then `systemctl enable --now somaloom-backup.timer`. The service runs as an operator with Docker and AWS IAM access. UTC schedule is 02:00 (05:00 Uganda time). `sudo bash tools/backup.sh` pauses API/worker writers, creates a consistent SQL dump and resource archive on encrypted EBS, unpauses services, calculates checksums and uploads files with SSE-KMS. An uploaded SHA256SUMS is the completion marker. Redis is a transport; durable job state belongs in PostgreSQL. Feature owners must implement safe requeue/outbox behavior before launch.

Verify a backup on an isolated recovery EC2 host: configure the same application commit and clean services/volume, retrieve a completed backup ID, then run `sudo bash tools/restore.sh --replace-database-and-resources BACKUP_ID`. It checks hashes, safely extracts resources, stops writers, restores SQL in one transaction, retains the old resource directory, runs compatible migrations and checks HTTPS readiness. Do not restore onto production as a test. Compare reference counts/checksums, sign in, open a reference, run an extraction/generation/export after those features are integrated, and record RPO/RTO. Never claim restore verified from script inspection alone.

## Rollback

Before every deployment, make and verify a backup; record old image digests and git SHA. Prefer additive expand/contract migrations and avoid destructive changes. If health checks fail, stop ingress and writers; inspect `docker compose logs --tail=200`. Rebuild/restart the prior reviewed SHA only if the schema is backward compatible. Otherwise restore the matching backup on a separate recovery instance, validate and move DNS. Do not blindly run `alembic downgrade` on live data. `0001` downgrade destroys the entire foundation schema and exists only for disposable migration CI tests.

## Observability and capacity

Poll `/api/v1/health` (process), `/api/v1/ready` (DB, Redis, worker heartbeat), HTTPS certificate expiry and `/api/v1/openapi.json`. Health remains unauthenticated for load balancers. Readiness returns 503 without its dependencies. Logs are stdout/stderr with request IDs in responses and unhandled-error records; do not log request bodies, credentials, source contents or prompts by default. Use Docker log rotation (10 MB, 5 files) and forward logs to CloudWatch. Alert on readiness failures for 2 minutes, worker heartbeat expiry (60 seconds), failed backup timer, absent daily backup, disk >80% (critical 90%), memory >85%, failed jobs and certificate <14 days. Configure CloudWatch Agent disk/memory collection on the actual instance; infrastructure alerts remain a launch prerequisite until tested.

Rate limits: Nginx 20 requests/s per client, API 600 requests/min, login 10/min, Redis-backed and fail closed. API trusts Nginx's overwritten X-Real-IP only in production; never expose its listener directly to the public internet. Queue tasks must be trusted because RQ serialization executes trusted Python jobs. Workers must not run user-supplied shell commands. TLS terminates at Nginx on private Docker networking; use TLS connections if moving DB/Redis to another host.

Staging workflow currently verifies an already deployed HTTPS origin. Automated deployment requires an actual staging host, restricted SSH/SSM and environment protection; no fictitious deployment workflow is presented as operational.

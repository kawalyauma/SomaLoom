# EC2 deployment and private staging

## Actual private staging (2026-10-26)

- Instance: i-0ec4689316dbd2d9d, eu-central-1, m7i-flex.large (8 GiB); name somaloom-beta-ad3966cd.
- Dedicated profile: somaloom-beta-ad3966cd. SSM management, release-object reads, backup-prefix reads/writes, KMS only via S3 and metrics only in SomaLoom namespace. Containers cannot inherit the host role through IMDS (v2 required, hop limit 1).
- Security group sg-076298a07b32a6d28 starts with zero inbound rules. PostgreSQL/Redis have no public published ports. No existing production or mobile-app instance was modified.
- Encrypted root disk 30 GiB and dedicated encrypted persistent data disk 60 GiB mounted at /srv/somaloom-data. Application and secrets under /opt/somaloom and /etc/somaloom; .env is root-owned mode 600 and absent from Git.
- Private versioned KMS-encrypted S3 bucket: somaloom-beta-ad3966cd-482146446766-eu-central-1. Block-public-access and TLS-only policy enabled. Release archive and backup objects are separate prefixes.
- Actual API/worker/dispatcher/web/PostgreSQL/Redis/Nginx images built; migrations applied as a controlled startup service; all seven long-running services passed Docker health checks. Nginx HTTPS/API readiness returned ready. Browser and off-instance restore tests passed; details and remaining real-provider gates are tracked in RELEASE_ACCEPTANCE.md.
- The account rejected t3.large because it permits only Free Tier-eligible types. The provisioning operation resumed its existing IAM/S3/SG resources and launched eligible m7i-flex.large; no duplicate instance was created.

No public application URL is claimed. The owner has not supplied a hostname, DNS zone, public TLS certificate, dedicated AI credential/runner or Telegram credentials. Private HTTPS uses a short-lived self-signed localhost certificate. Access from an authorized administration machine:

```bash
aws ssm start-session --target i-0ec4689316dbd2d9d   --document-name AWS-StartPortForwardingSession   --parameters '{"portNumber":["443"],"localPortNumber":["19443"]}'
```

Open https://localhost:19443 through that tunnel with the staging CA trusted for testing. This is a local tunnel endpoint, not a public deployment URL. Test credentials are kept outside the repository; do not paste them into logs or chat.

## Reproducible setup

Review tools/provision_staging.py and infra/ec2/staging-bootstrap.sh. Create a reviewed `git archive`, then run the provisioner with --archive, --subnet and --vpc; it prints the plan unless --apply is provided. It creates NEW resources only, journals partial provisioning, and supports --resume verification/staging.json after a launch error. Never reuse another production instance or the mobile-agent role. Inspect AWS quotas and Free Tier restrictions before choosing --instance-type.

Staging Compose layers are compose.yaml, infra/compose.production.yaml and infra/compose.staging.yaml. Production additionally requires owner-managed DNS/TLS and approved configuration. EBS is the default durable store. Optional SOMALOOM_STORAGE_BUCKET and SOMALOOM_KMS_KEY_ID must be shared by all services if S3 object storage is selected. The host scanner signature directory is mounted read-only and nonsecret signature files must be readable by UID 10001. Missing or broken scanning rejects uploads.

Nginx resolves api/web through Docker DNS with a 10-second refresh, so replacement containers do not leave cached upstream addresses. After changing mounted Nginx configuration, recreate or reload Nginx and verify HTTPS. Never count Docker's healthz alone as application acceptance.

## Deploy and rollback

1. Run local/native tests, dependency/secret scans, web build and Docker build. Record the exact reviewed release tree.
2. Upload the archive to the private release prefix. On the staging host, retain the previous release archive/image IDs and take a verified encrypted backup before a migration-bearing update.
3. Extract into a new release directory for production (the disposable staging bootstrap uses /opt/somaloom). Keep .env and data outside the archive. Build images; run the migration service once; then start app/worker/dispatcher/web/Nginx and wait for health checks.
4. Verify login, tenant denial, upload/scanner, stream/RQ processing, research, reviewed PDF/DOCX and provider behavior. Verify deployed code and migrations match the intended release.
5. For an application rollback, point the release directory at the retained compatible image/release and restart. For incompatible data/schema changes, restore the verified backup into a NEW recovery environment and validate before promotion. Do not downgrade feature migrations against live data.

The original tools/deploy.sh enforces a dedicated mounted data volume, production HTTPS settings and certificate files. Use it only after reviewing staging-specific scanner/monitor layers. See BACKUP_RESTORE.md for restore approval boundaries. CloudWatch health/disk/status alarms exist for this staging host; notification delivery remains unconfigured pending an owner-provided destination. No unrestricted public launch until the acceptance matrix's release blockers are cleared.

## Verified operations

The daily backup and per-minute monitoring timers are installed and active. Actual backup `20261026T212247Z-a9af3e7e` restored into a disposable PostgreSQL environment: 39 tables, two QA users, five original SHA-256 checks and four PDF/DOCX structure checks passed. A live browser completed login/upload/edit/review/download at desktop/tablet/mobile widths. Real RQ research found five permitted fixture sources. These results do not imply successful real AI generation.

Temporary owned-site HTTP access was restricted to the administration host and removed after the CLI test. The security group was verified empty again. No public beta URL exists. QA credentials remain in a mode-600 file outside Git and are not part of the release archive. The source repository, export logs and backups contain no real student data or private textbooks.

## Review and release references

- [Master integration PR #17](https://github.com/kawalyauma/SomaLoom/pull/17) (draft; main unchanged).
- [Verified integration snapshot 8f3704d9](https://github.com/kawalyauma/SomaLoom/commit/8f3704d9edfddf3ca0e4c1c78e16d6f4b3a8fc8f). The published tree matches tested local integration snapshot 8756cf5834d64ae12974ea7ef6351e58b5a5984e; original PR heads are preserved as ancestry.
- Detailed local integration commits are retained on `integration/somaloom-release-local-20261027`; no work was discarded or force pushed.

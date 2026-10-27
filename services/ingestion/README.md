# SomaLoom ingestion (Agent 2)

Feature branch: `agent/02-ingestion`. **Depends on Agent 1** (FastAPI, authentication,
`app.core.models`, object storage and Redis/RQ). No central schema or migration files
have been replaced. Agent 1 must incorporate
`db/proposals/agent-2-ingestion.sql` into the ordered Alembic history.

## Installation and registration

Install `pip install -e '.[dev]' -r services/ingestion/requirements.txt`.
In Agent 1's `apps/api/app/main.py`, register:

```python
from services.ingestion.router import router as ingestion_router

app.include_router(ingestion_router, prefix="/api/v1")
```

Run migration **before** exposing API. Start existing RQ worker, plus a trusted,
single-leader dispatcher: `python -m services.ingestion.dispatcher`.
Keep Redis private, authenticated and durable (AOF). The worker process and API
must share the same DB, object-store configuration and secrets.

Set `INGESTION_S3_BUCKET` and `INGESTION_S3_KMS_KEY` in production; this feature
rejects local object storage in production. The local filesystem store is only
for development. Configure an EC2 IAM role for the bucket/KMS key, encryption,
bucket versioning and retention policy. `INGESTION_MAX_BYTES` (default 20 MiB)
and `INGESTION_MAX_FILES` (default 20) cap uploads.
`INGESTION_TENANT_MAX_BYTES` defaults to 5 GiB and
`INGESTION_TENANT_MAX_RESOURCES` defaults to 50,000, counted per school including
retained deleted originals. HTTP upload progress is
client-side `XMLHttpRequest.upload.onprogress` (or equivalent), not server polling.

**Security release gate:** Set `INGESTION_SCANNER_COMMAND` to an installed
antivirus program that accepts a pathname (e.g. `clamscan --no-summary`).
Exit code 0 is clean, 1 rejects the file, and other exits or timeouts
fail closed. **Production ingestion rejects uploads if no scanner is configured.**
Development without a scanner marks `scan_status=unscanned` in provenance/events.
Agent 3 must refuse unscanned input in production.
Expand hard quotas, storage cleanup and strict tenant-scope authorization as
an Agent 1 deployment hardening task.

## API

Authenticated `school_admin` or `teacher`: `POST /api/v1/resources/uploads`,
with multipart `files` (repeat for bulk), `license`, optional `title`, `source_uri`.
School admins additionally have:
`PATCH /resources/{id}`, `DELETE /resources/{id}`,
`POST /sources`, `POST /sources/{id}/disconnect`,
`POST /imports/web`, `POST /imports/{id}/retry` and
`POST /imports/{id}/cancel`.
Authenticated school users can `GET /resources`, `GET /resources/{id}`,
`GET /resources/{id}/download?version=1`, `GET /sources`,
`GET /imports/{id}` and `GET /jobs/{id}` (Agent 1 route).
Platform admins must explicitly join a school rather than supplying a tenant header.

```bash
curl -X POST http://localhost:8000/api/v1/resources/uploads \
  -H "Authorization: Bearer $SOMALOOM_API_TOKEN" \
  -F "license=operator-authorized" -F "files=@book.pdf"
```

Source definition:
```json
{"kind":"web","source_uri":"https://owned.example.edu/materials/",
 "license":"operator-authorized","domains":["owned.example.edu"],"paths":["/materials"]}
```

Follow with `POST /api/v1/imports/web` JSON:
```json
{"source_id":"SOURCE_UUID","url":"https://owned.example.edu/materials/",
 "max_pages":100,"max_depth":2,"delay":1,"dry_run":false}
```

Event contract: Redis Stream `somaloom:resource.available`, fields
`event_id` and `payload` (JSON), containing `tenant_id`, `resource_id`,
`version_id`, `source_id`, `source_type`, `object_key`,
`mime_type`, `sha256`, `license`, `original_url`, `permissions`
and `scan_status`. Outbox is transactionally created with version metadata.
Dispatch is at-least-once (duplicates share the same event_id); Agent 3 must
deduplicate by `event_id` or `(tenant_id, version_id)` and verify permission
and scan policy before fetching the object. A successfully delivered event is
**not** proof extraction has finished. No extraction consumer is included.

## Website CLI

```bash
python -m services.ingestion.cli web --url https://owned.example.edu/materials/ \
  --allow-domain owned.example.edu --allow-path /materials --max-pages 100 --dry-run

export SOMALOOM_API_URL=https://api.example.edu
export SOMALOOM_API_TOKEN=... SOMALOOM_SOURCE_ID=...
python -m services.ingestion.cli web --url https://owned.example.edu/materials/ \
  --allow-domain owned.example.edu --allow-path /materials --authorized
```

Crawl is bounded (max 1000 pages, max depth 8, minimum delay 0.5 seconds),
honors robots.txt, rechecks redirect hosts/paths, pins DNS resolutions to
globally routable addresses and rejects private/loopback/link-local/metadata
IPs. No credentials, CAPTCHA bypass or protected content are supported.
Checkpoints and report JSON are stored with mode 0600. Only crawl sites the
operator owns or for which explicit permission is held. A 5xx error records
failure; it does not authorize bypassing policy restrictions.

## Telegram webhook

Configure `SOMALOOM_TELEGRAM_BOT_TOKEN` and
`SOMALOOM_TELEGRAM_WEBHOOK_SECRET` as host secrets. Register a Telegram source
with `kind=telegram`, `chat_id` and `license`; only one active school may
claim a chat ID. Configure Telegram's `setWebhook` to the **HTTPS** endpoint
`/api/v1/imports/telegram/webhook`, setting Telegram's `secret_token` equal
to `SOMALOOM_TELEGRAM_WEBHOOK_SECRET`. Do not commit either value.

The Bot API receives **new** messages/channel posts only when the bot is
present and has access. Depending on group privacy mode, a bot may not see all
messages. It cannot read arbitrary historical group messages or private
conversations. Existing history requires separate user-consented access,
outside the scope of this connector. `getFile` on hosted Bot API has file-size
limits (commonly 20 MB for bot downloads); larger files must fail safely.
Repeated (chat ID, message ID) is deduplicated. Disconnect a source before
revoking the bot. Processing retries are bounded by job timeout; failures
remain visible in persisted records.

## Retention, permission and verification

DELETE is a **soft delete**: hides metadata and download endpoints but retains
version originals and audit evidence until an approved retention/purge policy
is implemented. Metadata corrections preserve immutable per-version evidence.
Storage upload can leave an orphan if the database transaction fails; a
scheduled orphan reconciliation job is required for production. Web and
Telegram source ownership is administrator-attested, not externally verified.

Current integration constraints: Agent 1 must register the router, apply
the schema proposal, install `python-multipart`, add PATCH/DELETE to CORS,
and configure a service for the dispatcher. Agent 3 must implement a Redis
Stream consumer with idempotency and a quarantine policy. GitHub Actions may
be billing-blocked: record tests run locally and do not claim a blocked CI pass.

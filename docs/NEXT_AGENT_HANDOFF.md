# NotesUG deployment handoff

Continue from GitHub branch `deploy/notesug-codex`, not the older `main` branch.
This branch contains the integrated application, NotesUG deployment, real Codex
inference, Telegram link connections, automatic archive, and statistics page.

## Live application

- https://somaloom.notesug.com
- Resource statistics: `/statistics` (navigation: Sources → Resource statistics).
- Telegram source connections, progress and original downloads: `/telegram`.
- Catalogued resources: `/library`.
- API: authenticated tenant-scoped `GET /api/v1/resources/statistics`.

The statistics endpoint combines school-scoped library counts with the private
broker's archive counts. Downloaded means completed source-message attachments;
available originals excludes quarantined files. Forwarded files share an S3 object,
so unique storage bytes differ from the sum of source bytes. Discovery totals grow
until the ten-year scan completes. The recent activity table uses metadata update
dates, including library acknowledgements; it is not an immutable download audit.
An unavailable broker yields a warning and unknown archive counts, not zero counts.

## Runtime and deployment

Application EC2: `i-0ec4689316dbd2d9d`, eu-central-1, `/opt/somaloom`, managed by SSM.
Compose overlays must ALL be included:

```sh
docker compose --env-file .env -f compose.yaml \
  -f infra/compose.production.yaml -f infra/compose.staging.yaml \
  -f infra/compose.codex.yaml -f infra/compose.public.yaml \
  -f infra/compose.telegram.yaml config --quiet
```

API/worker/importer Python files are mounted read-only. Restart affected services
after replacing files; rebuild `web` for frontend changes. API and worker images
also need rebuilding when adding dependencies or new unmounted modules. Do not
remove the Codex overlays or overwrite `/srv/somaloom-data`. The importer uses a
2 GiB memory limit because ClamAV's definitions exceed 1 GiB during scanning.

Private Telegram broker: EC2 `i-07da5cc86cc4e9280`, private `172.31.23.34:3012`.
Systemd `somaloom-telegram-account`, running as `codexagent`.
Runtime code `infra/telegram/{account_broker,download_engine}.py` is installed into
`/home/codexagent/.config/somaloom-telegram/`. Its SQLite history/transfer queue lives
there; preserve it. Owner Telegram session resides on encrypted storage under
`/srv/somaloom-data/telegram-sessions/`. Restart broker after updating its Python
files; pending batches and checkpoints resume automatically. Use the existing
session; do not log into another Telegram account or ask for numeric group IDs.

Archive S3: `somaloom-telegram-482146446766-eu-central-1`, private AES256 encrypted,
versioned, regional endpoint with SigV4 signed original-download URLs. Ten files
transfer concurrently, groups rotate batches, history covers ten calendar years,
and separate polling discovers new uploads. All accessible document types and
sizes archive; only supported bounded scanned files enter the library. Existing
school library quotas and source rights checks still apply. No automatic expiry
of completed originals. Standard S3 storage/request/egress billing applies.

Secrets, `.env`, browser logins, private keys and live session databases are NOT in
Git. Existing host configuration and Secrets Manager supply them. See
`NOTESUG_DEPLOYMENT.md`, `TELEGRAM_LINKS.md` and `infra/compose.telegram.yaml`.
Do not overwrite separate uncommitted work in the mobile server's workspace repo.

## Validation

- `python3 -m unittest discover -s tests -p 'test_telegram*py' -v`
- Production Next.js build (includes TypeScript checking).
- Live authenticated statistics endpoint, counter reconciliation and original-file
  SHA256 checks. Archive/history backfill is a continuing background job, not a
  completed historical import.

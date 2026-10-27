# NotesUG deployment — 2026-10-27

Owner-authorized authenticated beta: https://somaloom.notesug.com.

## Applied changes

- Added a DNS-only A record in the owner's Cloudflare dashboard, pointing `somaloom.notesug.com` to the existing SomaLoom server at `18.185.148.248`. Existing NotesUG records were preserved.
- Reused EC2 `i-0ec4689316dbd2d9d`, its encrypted root/data disks, database and resources. No new EC2 instance was created.
- Took pre-change encrypted backup `20261027T035431Z-3718a55a`. No schema migration or destructive database change was performed.
- Installed a publicly trusted Let's Encrypt certificate, initially expiring January 25, 2027, with a renewal timer and Nginx reload hook.
- Enabled only public TCP 80/443 on the SomaLoom security group. Application/DB/Redis/inference listeners remain unpublished or loopback-only.
- Set the allowed browser origin to `https://somaloom.notesug.com` and replaced the private QA Nginx configuration with `infra/nginx/public.conf`. The owned-site QA route is absent from the public configuration.
- Created a real NotesUG school administrator, `admin@notesug.com`, in a separate NotesUG tenant. Disabled the two synthetic QA login accounts; their verification records remain retained and isolated.

## AI runtime

The owner explicitly requested their current Codex account/version. This authorizes using the same account in an independently isolated inference runtime; it does not transfer the mobile agent's AWS role, workspace, session history, or Telegram credentials.

- Codex CLI 0.164.0, model `gpt-6.1-sol`, using the owner's ChatGPT account. Account quota is shared with the owner's other Codex sessions.
- API and worker use an exec-compatible HTTP client in `infra/codex/runner-client.py`. A private bearer token authenticates calls to the isolated service; the actual CLI's help output is returned for compatibility verification.
- The inference container is UID/GID 10002, has a read-only root filesystem, no added capabilities, no privilege escalation, a 1.5 CPU / 1536 MiB / 128 PID limit, an ephemeral request directory, and no published host ports.
- Shell, Code Mode host, Code Mode, and sleep tools are disabled for inference. Only the prompt and JSON schema cross the application boundary.
- The container has no application/DB/Redis/AWS/Telegram credentials, no resource-store mount, no Docker socket, and no AWS metadata route. It has its own credential directory on encrypted EBS so Codex can refresh the owner-authorized account session.
- Internet access goes through a CONNECT-only allowlist proxy for ChatGPT/OpenAI endpoints. Private destination addresses and arbitrary destinations are denied. Container networks isolate inference from the normal database network.
- Bootstrap credentials are stored in AWS Secrets Manager. The host has narrow read access to the two deployment secrets; containers cannot inherit the host IAM role. Owner login material is saved privately outside Git on the operator workstation.

Use all overlays when recreating this deployment:

```sh
docker compose --env-file .env \
  -f compose.yaml -f infra/compose.production.yaml -f infra/compose.staging.yaml \
  -f infra/compose.codex.yaml -f infra/compose.public.yaml -f infra/compose.telegram.yaml up -d
```

Do not omit the Codex/public overlays when recreating application containers. Existing backup pause/exec operations retain their project/container identity.

## Executed checks

- A real isolated Codex request returned `SomaLoom Codex connected`, with JSONL events received.
- Actual `CodexCLIProvider` → generation orchestrator execution produced one lesson-notes section, six source-supported blocks, and one known source reference. The supplied deployment-verification passage is original CC0 test content, explicitly not an official curriculum. The draft remained `awaiting_review`; warnings about educator verification were preserved.
- Inference rejected an unauthenticated request. Live checks verified non-root execution, immutable root filesystem, absence of application secret mounts/runtime socket, blocked metadata, and blocked unapproved outbound traffic.
- Public DNS was checked at Google and Cloudflare resolvers. Public HTTPS homepage returned 200; `/api/v1/ready` reported database, Redis and worker ready. TLS hostname/trust validation passed without bypasses.
- Owner API login succeeded, issued a Secure cookie, and listed only the NotesUG school. Unauthenticated resources returned 401; a cross-origin write returned 403.
- The deployed sign-in page loaded in the browser over valid HTTPS. Prior full browser publishing/tenant tests are recorded separately in RELEASE_ACCEPTANCE.md.
- Existing `https://notesug.com/` and `https://notesug.com/agent/` both returned 200 after deployment.

## Remaining boundaries

This is an authenticated beta, not a blanket production/academic acceptance claim. Official curriculum content, teacher validation, semantic retrieval, broader extraction accuracy, alert delivery, and production capacity require their own evidence. The Telegram personal account has been authorized separately on the mobile-agent host; link-only account-backed group connections are now deployed (see TELEGRAM_LINKS.md); account-history document importing remains unfinished.

Codex account use consumes the same subscription allowance as the owner's other sessions. Inference can time out or hit account limits. Reauthenticate the isolated runtime if the owner revokes its account credentials. Do not replace the runner with the privileged mobile agent or mount host credentials into the app.

### Automatic Telegram archive

Deployed 27 October 2026: four existing Telegram sources automatically backfill
accessible history to 27 October 2016 and poll new uploads. Up to ten original
files transfer concurrently into private, versioned, encrypted bucket
`somaloom-telegram-482146446766-eu-central-1`. Progress and original download links
are visible at `/telegram`. `telegram-importer` handles source synchronization
and scanned library ingestion. See TELEGRAM_LINKS.md for runtime/recovery details.

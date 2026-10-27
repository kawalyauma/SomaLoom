# Telegram link-only connections — 2026-10-27

The deployed Telegram page accepts one group/channel link such as `https://t.me/TeacherInUganda`. It has no numeric-ID input, license field or permission checkbox. Telegram entity IDs are resolved and stored internally through the already-authorized personal account.

## Connection architecture

The account session remains private on the agent host. The SomaLoom API does not receive account API credentials or a session file. A narrow resolver service accepts only a bounded canonical Telegram link, resolves it via Telethon, and returns its group title and internal peer ID. The service offers no commands, credential retrieval, account login, group joining, or message-sending endpoints.

- Resolver: private `172.31.23.34:3012`, systemd `somaloom-telegram-account`, service user `codexagent`.
- Transport: TLS with a pinned local certificate, bearer authentication, and security-group ingress only from the SomaLoom server's security group.
- Shared token: managed secret `somaloom/staging/telegram-broker-token`, mounted only into the SomaLoom API. The Codex inference runtime receives neither the token nor the Telegram session.
- Session: existing `/srv/somaloom-data/telegram-sessions/owner.session`, owner-only permissions, with a lock shared with the private authorization CLI.
- Public usernames, public post links, `t.me/s/` links, and existing accessible private invite links are normalized. Private invitations do not automatically join a group. Unknown/inaccessible groups return a clear connection error rather than an extra permission form.
- Connections and duplicate handling are school-scoped. Source-rights metadata defaults internally to `unknown`; connecting a link does not invent a license claim. Legacy bot integrations remain supported for existing API callers but are not the user-facing connection flow.

Add `-f infra/compose.telegram.yaml` after the Codex/public overlays whenever recreating the deployed API. The resolver systemd unit is installed separately on the account host. Its TLS key and token are not in Git; `broker-ca.pem` is only the public verification certificate.

## Verification

Three URL-boundary tests passed, covering canonical public/post/invite links and rejection of numeric input, misleading hosts, credentials in URLs, private targets and service links. The Next.js production build and TypeScript checks passed.

A real authenticated application request connected `https://t.me/TeacherInUganda` with only `kind` and `source_uri`; Telegram returned the title `Teacher in Uganda 🇺🇬`. A post link normalized to the same stored connection instead of creating a duplicate. The account connection check succeeded. The deployed signed-in browser page displayed exactly one Telegram-link input and the connected group's title/link, with no permission checkbox or numeric-ID prompt.

This change connects and verifies groups. Account-history document importing is still not enabled. The connection-check response states that explicitly; no documents were downloaded or imported as part of this connection test.

## Automatic archive (27 October 2026)

All active account-connected Telegram sources are synchronized every ten seconds by
`telegram-importer`. Each receives a frozen calendar ten-year cutoff, a durable
history cursor, and a separate cursor for new messages. Ten resources transfer
concurrently per batch; source batches rotate fairly. Telegram rate limits and
interrupted transfers retry automatically. Disconnecting a source stops its work.
Only history still accessible to the connected account can be retrieved.

The private account broker streams every document/photo, regardless of extension
or declared size, into encrypted private S3 storage. No whole-file staging on EC2
is required. Per-school Telegram media keys deduplicate forwarded originals.
SQLite checkpoints survive broker restarts; completed S3 objects are reused.
The regional S3 endpoint and Signature V4 are required for download links.

The Telegram page polls progress and paginated file lists every ten seconds and
serves tenant-authorized original downloads through two-minute signed URLs.
Supported documents up to the library extraction limit are scanned and indexed;
other originals remain in the archive. Existing library quotas and unknown source
rights remain in force. Archive storage and requests incur normal AWS charges.

Runtime: `infra/telegram/download_engine.py` alongside `account_broker.py` under
`/home/codexagent/.config/somaloom-telegram` on the mobile agent server. Its
`somaloom-telegram-account` systemd service owns the persistent Telegram session.
Deploy all Compose overlays including `infra/compose.telegram.yaml`; restart the
API, worker and telegram-importer after changing their mounted Python modules.

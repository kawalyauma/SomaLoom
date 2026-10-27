# GitHub resource requests and imported images

Production generation requests use `execution_mode=github`. “Generate resource” stores the original request, prepares the permitted evidence, commits reference PDF/DOCX files with a request prompt and output schema, and only then opens a GitHub issue in `kawalyauma/SomaLoom`. No model inference is called to prepare or synchronize the request.

Any agent can work on an issue and keep partial work in its request folder. Final JSON belongs at `resource-bank/results/<request-id>/result.json` on main. The server imports it through the existing family-specific validators and publishing normalization. Invalid output remains a failed request needing revision; it is never advertised as complete. Result checksums prevent duplicate documents. Closing an issue alone does not complete work.

“My work” preserves the same request ID, source snapshot, activity, progress and issue link across handoffs and retries. Local AI execution, when explicitly selected through the API, also checkpoints evidence and completed provider calls. Its retry does not reset progress to zero. Old upstream failures retained only a generic code; the isolated runner now distinguishes usage limits, rate limits, schema/context errors and authentication errors.

## Synchronizer

`infra/resource-bank/bridge.sh` runs from the `somaloom-resource-bank.timer` systemd timer, 30 seconds after each completed cycle. It prepares packets using the app, runs a short-lived trusted sync container, and imports receipts/results. The sync container mounts only the bank folder; it receives no application database, AWS account or Codex credential. It uses a fine-grained GitHub token scoped to this repository's Contents and Issues. Hosted Actions cannot run because of the account billing lock, so the direct server synchronizer is the active implementation.

The token is stored privately in `<DATA_ROOT>/resources/resource-bank/.github-token`, outside all committed outbox files. The approved token expires November 26, 2026. Renew it with the same narrow permissions before expiry. One-time HTTPS setup uses `.setup-key`, a short-lived random capability, which is deleted immediately after successful connection. Tokens are never returned by an API or placed in request metadata. Check systemd logs and `connection-status.json` if synchronization stops. Packets survive any connection outage.

Source files are content-addressed and checksum-checked. Packet creation is atomic, remote publication uses a non-forced commit, and issue lookup includes a request marker to recover safely after a crash. Cancellations retain their files and close an already-created issue as not planned.

## Image workspace

`/images` creates deterministic, editable copy prompts from a user's description and optional linked generation. The user generates an image with their preferred external tool, then imports PNG, JPEG or WebP. There is no image-generation API call or model quota consumption in this flow. Imports are bounded, decoded and stored as clean PNGs, scoped to the school. A document attachment creates a new saved version. Its reference includes the image checksum, so later imports cannot silently change old document versions. Editor previews and PDF/DOCX asset resolution support these imported illustrations.

Migration: `c61a20261027` adds `image_requests`. Run the standard migration/grant command before deploying API and web. Tests cover packet idempotence, source checksums, issue receipts, external result import, AI-call checkpoints, image validation, school isolation, attachment versions and rendering resolution, plus generation selection/history and master schemes.

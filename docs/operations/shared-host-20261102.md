# Shared NotesUG AWS host

Updated 2 November 2026. NotesUG, the Codex/AGY agent, SomaLoom and Ledgerly share the existing NotesUG host in eu-central-1. Public domains and existing account authentication are retained.

- Host: `3.64.173.11`; instance `i-032e573103f4ae75f`; 8 GiB RAM, 150 GiB gp3.
- NotesUG: `/home/ubuntu/ulibtech`, original `edushare` Docker deployment.
- Codex/AGY web app: `/opt/codex-mobile`; shared working directory `/home/codexagent/workspace`; SomaLoom working checkout `/home/codexagent/workspace/SomaLoom`.
- SomaLoom: `/opt/somaloom`; data `/srv/somaloom-data`.
- Ledgerly: `/opt/ledgerly/source`; AI sessions and workspaces `/var/lib/ledgerly-ai`.
- Active runtime manifests: `/opt/consolidation-20261102/somaloom/compose.consolidated.json` and `/opt/consolidation-20261102/ledgerly/compose.consolidated.json`. These private runtime files contain environment secrets and must not be committed or printed.

## Operation

Use the existing deployment records for the shared host. Do not replay historical migration/provisioning scripts or launch another dedicated agent instance. The old source databases are frozen migration checkpoints: never copy them over a shared-host database after it has accepted new writes.

```bash
cd /home/codexagent/workspace/SomaLoom
codex
```

AGY is already managed by `agy-worker.service`; interact through the web app's Antigravity model selection. The Terminal tab remains available with the copyable folder guide.

```bash
sudo systemctl status codex-mobile agy-worker somaloom-telegram-account
sudo systemctl status somaloom-resource-bank.timer
sudo docker ps
```

For a container update, use its active consolidated manifest and preserve the current environment, mounted data, authentication and image versions. Existing source Compose files retain their historical source port mappings; using them unmodified can collide with other apps on the shared host. Ledgerly's provider images `ledgerly-ai-codex:local` and `ledgerly-ai-claude-code:local` are required by its AI gateway even when no provider container is currently running.

The existing resource-bank timer has moved to this host. The previously disabled P5/P6 generation timer remains disabled; this migration does not create additional content-generation agents or schedules.

## HTTPS and recovery

The existing NotesUG nginx serves the domains and proxies each app internally. TLS verification remains enabled for the SomaLoom backend. Certificates renew using the central host's ACME webroot, with the `consolidated-apps` deploy hook updating the relevant frontend/backend certificate files.

Recovery-image identifiers, source instance details and execution reports are private under `/opt/consolidation-20261102/` and the local migration record. Restore snapshots to a separate recovery environment first; do not start a frozen source as authoritative after the live host has accepted writes. Do not publish credentials or private runtime manifests.

AWS compute is consolidated; object storage, backup snapshots and data-transfer charges remain separate. Four onboarding activities earned $80 AWS credits. The Bedrock activity is not complete because AWS rejected inference with a daily-token quota error. The AWS account was not upgraded to a Paid plan.

# Agent 5 — AI Orchestration Engine

## Status and integration

Implements bounded, schema-constrained generation and source-grounded quality checks
on top of Agent 1's `BackgroundJob`, `generation_jobs`, `generated_documents`,
`document_versions`, `evidence_links` and RQ `somaloom` queue.
PR must be integrated **after foundation PR #9**. Does not add schema/migration heads,
does not implement Agent 6/7 templates or Agent 8 rendering/review approval.

Feature router is `app.routes.generation:router`, mounted at `/api/v1`.
The sole Agent-1-owned edit is a two-line registration in `app.main`;
Agent 1 should confirm this when integrating.

## API contract

- `POST /api/v1/generations`: school_admin/teacher, 202. Body:
  `{document_type,curriculum_id,subject_id,level_id,topic_ids,options,resource_filters}`.
  Optional `X-Idempotency-Key` max 128 chars, scoped to actor and tenant;
  conflicting payload gives 409.
- `GET /api/v1/generations/{id}`: authenticated, tenant scoped, job/stage/progress;
  404 for missing/cross-school.
- `GET /api/v1/generations/{id}/draft`: authenticated, tenant-scoped, latest structured
  version (404 until generated).
- `POST /api/v1/generations/{id}/cancel`: teacher owner or school admin, terminal
  cancellation.
- `POST /api/v1/generations/{id}/retry`: teacher owner or school admin, retry failed job
  at most twice.
- No publish/approve endpoint: Agent 8 owns teacher review and approval.
  Successful generation means draft awaiting review, never public publication.

Document kinds: `lesson_notes`, `scheme_of_work`, `lesson_plan`, `teacher_guide`,
`exam`, `test`, `quiz`, `marking_guide`, `assignment`, `worksheet`.
Instructional/assessment template details remain Agent 6/7's responsibility.

## Agent 4 — exact evidence integration contract

`services.generation.schema.EvidenceBundle`:
```json
{
  "outcomes": [{"id": "UUID", "code": "P1", "description": "Describe..."}],
  "passages": [{
    "id": "UUID from evidence_links", "outcome_id": "UUID from outcomes",
    "quote": "permitted excerpt", "source_title": "existing title or null",
    "source_uri": "known provenance URI or null", "license": "recorded license or null"
  }]
}
```

Temporary `retrieve_evidence()` queries existing `learning_outcomes` and
`evidence_links` by school. **Until Agent 4's topics/outcomes mapping is supplied,
`topic_ids` must contain actual learning outcome UUIDs** from the chosen curriculum.
Unknown IDs fail as `topic_outcome_mapping_missing`, not invented outcomes.
Agent 4 may replace retrieval with its multi-vector/search implementation using the
exact schema, preserving tenant checks and quote/page provenance. The worker retrieves
evidence only in the tenant scope established from the stored authenticated job.
If no permitted evidence exists, the resulting section is flagged unverified.

The model creates one section per outcome and selects bounded relevant citations.
Returned citation UUIDs must belong to the excerpts actually presented to that section;
unknown IDs are removed and reported. Source text is inert JSON data and no tools
or terminal commands are exposed to the model. Unsupported content and contradictions
require teacher review. Unsupported math is **not** claimed as mathematically verified.

## Runtime configuration

Agent 1 `AI_PROVIDER` values: `disabled` (default), `codex`,
`api`, `codex_with_api_fallback`.

- `AI_MODEL`: explicit supported model name (provider-dependent)
- `AI_CODEX_ISOLATION_ATTESTED=1`: explicitly required in production only after\n  an operator has verified container and credential separation on the real host.\n- `AI_CODEX_RUNNER`: absolute executable path to a **hardened, independently
  isolated Codex runner** with exec CLI semantics. Not a simple alias to `codex`.
- `AI_API_KEY`: dedicated server-side managed inference API key; not a login session.
- `AI_API_ENDPOINT`: optional HTTPS OpenAI-compatible chat completions URL.
  Default OpenAI chat completions endpoint. Only set to operator-trusted hosts.

Use separate credentials and quotas for AI calls. No production task should inherit
AWS/Telegram/DB credentials or a developer's `~/.codex`. API provider should run in
a separately restricted worker process: the API key exists there, not in generated prompts.

**Production CLI isolation gate:** the supplied runner must be a dedicated, unprivileged,
single-purpose container or tightly isolated process with clean environment and HOME,
ephemeral writable directory, read-only source/schema mount, OS CPU/memory/PID limits,
no accessible host/container runtime socket, no shared host mounts, no AWS metadata route,
and network egress limited to the required Codex endpoints. Verify these controls with
the actual host security policy. `--sandbox read-only` is defense in depth, **not**
a sufficient substitute for the runner. Provider checks `codex exec --help` for
exact version-supported flags before running, times out/terminates the process group,
caps stdout and stderr, sanitizes error classes, and restricts concurrency.
The model receives no shell/tools from resource text. A configured runner path
without verified OS policy is **not production clearance**.

Codex CLI account authentication, rate limits, cost, latency, and license/service
terms may not permit general public multitenant server operation. Enable
`AI_PROVIDER=api` for a dedicated independently authenticated service or use
`codex_with_api_fallback` for bounded fallback. Cost is null when the provider has
no reliable rate metadata; token counts are recorded when returned by the API.

## Job recovery and reliability

`background_jobs` rows are durable before RQ enqueue. A dispatcher can recover
queued jobs if Redis was down during the initial enqueue. Run
`python -m services.generation.dispatch` as an operator-managed scheduled task
(e.g. systemd timer) every minute; run it under the same trusted worker account.
This is a DB-backed outbox scan, not a guarantee of atomic Redis/DB delivery.
Duplicate queued messages are guarded by stable RQ IDs, terminal-state checks and
idempotent document persistence. A crashed active worker may leave a `running` job;
manually inspect/reconcile before re-queuing (automatic lease recovery is a
**pre-release reliability gate**, not yet claimed complete). Cancellation is checked
between phases, not guaranteed immediate while an external provider call is in flight.

Versions are persisted in `document_versions` (initial version 1).
Agent 8's subsequent teacher changes/approvals should create version 2+ and reviews.
Internal stages are `starting/researching/compiling/validating/saving/awaiting_review`;
the shared public job states remain `queued/running/succeeded/failed/cancelled`.

## Local verification / release gates

From a checked-out branch with Agent 1 dependencies installed:
```bash
python -m pytest -q tests/test_generation.py
python -m pytest -q
python -m compileall -q services/generation services/ai apps/api/app/routes
ruff check services/generation services/ai apps/api/app/routes tests/test_generation.py
python -m services.generation.dispatch
```

The automated suite uses stub AI and SQLite from Agent 1's fixtures. It does not
measure correctness of generated scientific facts. Run a real controlled smoke
test on a staging host with allowed curriculum outcomes, two licensed source
records and dedicated credentials; check the stored `document_versions.body` JSON,
citation IDs, quality report and review status. Check auth expiry, network failure,
malformed output, timeout, cancellation, provider switch, cross-tenant denial, job
recovery, and resource quotas in the real sandbox. Document Codex version and flags
from the installed runner, do not assume flags on other installations.

**Unverified acceptance gates:** no real Codex executable/authenticated endpoint or
live PostgreSQL/Redis is available in this coding environment; a real source-grounded
Codex smoke test, actual isolated runner policy, deployment/EC2 checks, and full
end-to-end verification remain outstanding. GitHub-hosted CI is intentionally not
used because the project account has a billing restriction. Never represent mocked
test outputs as a real Codex generation.

## Visuals and source rights

Agent 4 may return `visuals` in an `EvidenceBundle` using `{id,outcome_id,kind,caption,page,source_uri}`.
The interim bridge selects only visual assets that share the tenant, extraction and
page of a licensed cited evidence block. The model may reference a visual by an
existing `asset_ref`, but unknown asset IDs are removed; Agent 8 must load the
asset by ID under the same tenant. Mathematical equations are stored as LaTeX,
and a limited independent integer arithmetic validator flags obvious false
equalities. Complex algebra, diagrams and scientific correctness remain human
review requirements.

Passages without declared licensing metadata or with an `unknown` license
are excluded; operators must verify actual redistribution and processing rights.
The generator does not treat a claimed metadata label as legally sufficient
permission without Agent 2's ingestion policy.

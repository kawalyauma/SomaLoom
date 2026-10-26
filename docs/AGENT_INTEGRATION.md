# Agent integration contract v1

## Ownership

| Agent | Owned folders |
|---|---|
| 1 | root config, infra, contracts, db/migrations, apps/api/app/core, apps/api/app/auth, API composition |
| 2 | services/ingestion; resource library/import routers |
| 3 | services/extraction |
| 4 | services/knowledge |
| 5 | services/ai |
| 6 | services/templates |
| 7 | services/assessment |
| 8 | apps/web, services/rendering, services/export |

Feature routers live in their service folder and export `router`. Coordinate app registration with Agent 1. Do not replace central contracts or migration heads. Propose migrations in `db/proposals/agent-N-*.sql`; Agent 1 reviews and integrates. Avoid dependencies on unmerged feature branches.

## HTTP and errors

REST `/api/v1`, UUID IDs, ISO-8601 UTC timestamps. Lists use `{items,page,page_size,total}`, with page >= 1 and page_size <= 100. Errors use `{error:{code,message,details},request_id}`. Validation returns 422; unauthenticated 401; forbidden role 403; inaccessible tenant objects 404. All responses include X-Request-ID. OpenAPI is generated into `contracts/v1/openapi.json` from the working app.

## Authentication and tenancy

Opaque expiring sessions, server-side hashed tokens, HttpOnly cookies or Bearer authorization. Browser mutations require an allowed Origin; cookies are Secure in production, SameSite=Lax. Roles: platform_admin, school_admin, teacher, reviewer. Derive tenant_id from authenticated user, never from untrusted headers. Platform admin access is explicit. Every feature query must filter by tenant and every child relation must enforce equal tenant via composite foreign keys. Background workers revalidate job ownership. Never expose credentials or session hashes.

## Database

PostgreSQL 16+ with vector extension. snake_case plural tables; UUID IDs; timezone-aware UTC created_at/updated_at; tenant_id references schools.id. Schema edits are additive where possible. No auto-create at API startup. Alembic runs once as a deployment step. Secrets belong in deployment configuration, never resource metadata or audit payloads.

## Jobs

RQ queue `somaloom`, Redis durable AOF. Persist a job row before enqueue; feature owners must implement a transactional outbox for reliable feature submission. Payloads contain job IDs, not arbitrary code or credentials. Status: queued/running/succeeded/failed/cancelled; progress 0..100; error is sanitized; finished_at for terminal status. Redis is private and authenticated because RQ uses trusted serialized jobs. Workers must be idempotent, bound retries/timeouts, and persist failures. Platform provides worker health heartbeat and authenticated status lookup; feature submission is not implemented here.

## Documents and evidence

See `contracts/v1/schemas.py` and generated JSON Schema. Pipeline: Resource → ResourceVersion → Extraction → ContentBlock/VisualAsset/Equation → EvidenceLink → GenerationJob → GeneratedDocument → DocumentVersion/Review → Export/Publication. Retain source URI, license, checksum and provenance. Store object keys, never host filesystem paths in public payloads. Equations retain LaTeX; document bodies use structured JSON with schema_version, sections and evidence IDs. Rendering belongs to Agent 8. Central fixtures for all 11 domain contracts are synthetic mocks, exposed only in development and clearly labeled.

## Git and integration

Branch from published main: `git switch -c agent/NN-name`. One PR per workstream, no force push to others' refs. Contract changes require an agreed PR; include schema migration and compatibility notes. Keep feature routers isolated. CI requires lint, unit tests, PostgreSQL migration/auth isolation integration tests, web build and Docker smoke tests. Every feature must test unauthenticated access, role denial, cross-tenant IDs, malformed inputs and retry behavior. A mock response is not acceptance evidence for a feature.

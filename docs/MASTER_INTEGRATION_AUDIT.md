# Master integration audit

Audit started 2026-10-26 UTC. Main: `cae10133377e2c184254e50fe7ca03a74ef0f493`. Integration branch: `integration/somaloom-release`. No GitHub jobs triggered; workflows remain manual-only. All eight PRs are open and unmerged. #11 is ready-status; the other seven are draft. Discussion timelines inspected: no review submissions or inline feedback returned; #9 has CI pause and Agent 8 integration requests.

## Dependency and risk map

Order: #9 foundation → #13 ingestion → #12 extraction → #10 curriculum/knowledge → #15 AI → #11 teaching + #14 assessment → #16 editor/export. Feature branches share the exact foundation head; integrate only feature differences and preserve original commits. Do not duplicate #9 through #15. Main remains stable.

Critical gates: native PostgreSQL/pgvector migration consolidation; resource event stream consumer; extraction-to-index handoff; topic/outcome identity mapping; canonical document format; authenticated frontend API shapes; licensed visual export; real isolated AI execution; backup/restore and HTTPS staging. Existing developer EC2 host has 2 GiB RAM; avoid workload interference with mobile app. Other running EC2 workloads are not deployment targets without inspection.

## PR inventory

### #9: agent/01-platform

- Target: `main`; base: `cae10133377e2c184254e50fe7ca03a74ef0f493`; head: `30c8c1f2a8aef9db45a1c29b79535546a28eac1e`.
- Status: draft; 89 changed files. Merge readiness: NOT VERIFIED.
- Local tests executed at initial audit: none. Reported author results below are historical, not acceptance evidence.

Provides the Agent 1 foundation for Issue #1: FastAPI sessions with Argon2 passwords, role/tenant checks and audit logging; 24-table PostgreSQL/pgvector Alembic schema; Redis/RQ worker; minimal Next.js sign-in; versioned OpenAPI/JSON Schema and 11 typed synthetic fixtures; Docker Compose, TLS proxy, restricted application DB role, immutable object storage, EC2 configuration and backup/recovery runbooks.

Validation executed:
- 16 local tests passed; 2 native service tests skipped in the default suite.
- Live Redis integration passed; a separate RQ worker executed a real queued task.
- Live production Next.js → FastAPI login/profile/logout and revoked-session denial passed using SQLite.
- Ruff lint/format, TypeScript and Next.js production build passed.
- npm production audit: zero vulnerabilities; Gitleaks tracked-file scan: no leaks.
- Development and merged production Compose configurations validated with Compose v2.40.3; shell/YAML syntax and contract regeneration passed.
- PostgreSQL-WASM supplemental test executed upgrade/downgrade/upgrade, pgvector/HNSW and restricted-role permission checks. Native PostgreSQL/psycopg remains unverified.

CI is blocked before execution: GitHub run 40376980274 reports “The job was not started because your account is locked due to a billing issue.” No CI job steps ran. Docker is unavailable locally. Resolve account billing and rerun CI to verify native PostgreSQL, actual image builds and container smoke checks.

External gates: EC2 access, DNS/TLS, encrypted EBS, S3/KMS/IAM, verified off-instance backup/restore, staging deployment and cloud alert delivery. Feature implementations remain with Agents 2–8. See docs/VERIFICATION.md for the acceptance ledger. This draft does not close #1 or claim production readiness.

### #13: agent/02-ingestion

- Target: `agent/01-platform`; base: `30c8c1f2a8aef9db45a1c29b79535546a28eac1e`; head: `b3b3419691e61cc111dab748edea20c737292f37`.
- Status: draft; 11 changed files. Merge readiness: NOT VERIFIED.
- Local tests executed at initial audit: none. Reported author results below are historical, not acceptance evidence.

## Scope — closes #2 when verified and merged

Agent 2 implementation on top of Agent 1's currently unpublished foundation. Includes:

- Bulk multipart uploads with chunked reads, signature/type/extension validation, per-file and tenant quotas, antivirus scanner gate for production, S3/LocalObjectStore originals, immutable version keys and SHA-256 deduplication.
- Tenant-bound resource listing, metadata editing, version history, authenticated downloads, soft deletion and auditing.
- Source allowlists, disconnect, Telegram Bot API webhook with shared-secret validation, chat/message dedup, persisted receipts, rate-limit backoff, error states, bounded manual retry and no historical-private-chat assumptions.
- Authorized web crawler and `python -m services.ingestion.cli web --url ... --max-pages 100 --dry-run` with pinned-public DNS, redirect/path checks, robots.txt, crawl budgets, retry/backoff, checkpoints and JSON reports.
- RQ web/Telegram workers, an ingestion dispatcher, persisted job records, at-least-once transactional outbox publishing stable `resource.available` events to Redis Stream `somaloom:resource.available`. Agent 3 must deduplicate by event ID.
- Feature-router endpoints, proposed PostgreSQL migration `db/proposals/agent-2-ingestion.sql`, tests and runbook.

### Integration dependencies — *not yet confirmed*
1. Agent 1: review and integrate additive migration proposal; install `python-multipart`; register `services.ingestion.router.router` under `/api/v1`; extend CORS for PATCH/DELETE; deploy API/RQ/dispatcher and configure S3/KMS/scanner.
2. Agent 3: consume Redis Stream with tenant/version/event ID checks and quarantine/scan enforcement.
3. Validate with a real PostgreSQL 16, Redis/RQ, S3, Telegram bot and **owned, explicitly authorized** site before release.
4. Add upload resumable transport/stronger scheduler backoff if required after beta.

### Verification
- Code and tests written: `tests/test_ingestion.py`.
- **Not executed here**: no checked-out GitHub branch available in this execution environment, and Redis/RQ/fakeredis project dependencies are unavailable locally. Test results are **unverified**, not passes.
- GitHub Actions are currently billing-blocked and must not be used as beta acceptance evidence.
- Command for a configured checkout: `pip install -e '.[dev]' -r services/ingestion/requirements.txt && pytest tests/test_ingestion.py -q && ruff check services/ingestion tests/test_ingestion.py`.
- No EC2 deployment or live Telegram import has been performed.

This PR is intentionally **draft**, based on `agent/01-platform` because Agent 1 is still outside `main`. Retarget to `main` after Agent 1 is merged. See `services/ingestion/README.md` for setup and authorization constraints.

### #12: agent/03-extraction

- Target: `agent/01-platform`; base: `30c8c1f2a8aef9db45a1c29b79535546a28eac1e`; head: `9a725e81ce82ee09dc7cf49d0986943547f51fea`.
- Status: draft; 19 changed files. Merge readiness: NOT VERIFIED.
- Local tests executed at initial audit: none. Reported author results below are historical, not acceptance evidence.

Implements Agent 3's multimodal document-intelligence workstream for #3, stacked on Agent 1's foundation branch `agent/01-platform` (PR #9), not on yet-unmerged `main`.

## Implemented
- Bounded PyMuPDF native/scanned PDF ingestion with OCR fallback, ordered source/page rectangles, heading hierarchy, table detection and page-local partial failure warnings.
- DOCX ordered paragraphs/tables, inline visuals, conservative OMML→LaTeX subset; HTML headings, lists, tables, embedded visuals and annotated MathML; educational image OCR.
- Source-/version-linked Pydantic blocks with deterministic IDs, confidence, review flags, license/provenance, asset content hashes and semantic section boundaries.
- Visual classification from actual captions; high-confidence source OCR labels; maps preserve observed title, legend, scale, orientation and always flag unverified boundaries.
- Native text math normalization (fractions, powers, radicals and supported LaTeX), optional MathText rendering syntax probe, exact PDF equation crop in original object storage, and original OMML/MathML retention for unsupported structures.
- RQ worker task and authenticated isolated feature router; immutable object-store JSON, idempotent job results, progress per PDF page, document retries, queue reconciliation, and checksum checking.
- Synthetic complete textbook passage HTML demo containing explanations, diagram, table and structured equation; PDF/scan/DOCX/HTML/math/map/tenant/evaluation test coverage and evaluation CLI.
- Safe, additive migration proposal `db/proposals/agent-3-extraction.sql` for a unique resource-version claim and transactional outbox. No central schemas or migrations changed.

## Local verification
**Not executed against this branch's checkout in the current execution environment.** GitHub Actions is unavailable due to account billing, and the execution container cannot retrieve the repository directly. Do not interpret synthetic fixtures or review heuristics as measured OCR, visual, or math accuracy.

Run locally:
```sh
python -m pip install -e '.[dev]'
python -m pip install -r services/extraction/requirements.txt
sudo apt-get install tesseract-ocr
pytest -q tests/test_extraction_engine.py tests/test_extraction_db.py tests/test_extraction_evaluation.py
python -m services.extraction.demo --output /tmp/somaloom-demo
python -m services.extraction.evaluation tests/fixtures/extraction/ground_truth.example.json
```
Metrics intentionally report `null` until verified reference/prediction pairs are supplied; no metrics are fabricated.

## Integration blockers / known limits
1. Agent 1 needs to register `services.extraction.router.router` in `app/main.py`, install extraction extras in API/worker images, and review the unique-index/outbox proposal. Current post-commit RQ enqueue + reconciliation is not fully atomic against concurrent submissions.
2. Agent 2 must emit authenticated/trusted `resource.available` events to `accept_resource_available`, using persisted tenant and version IDs. Agent 4 consumes normalized `document.v1.json` and honors `needs_review`. Agent 8 owns final editable OMML/typeset math.
3. Complex vector-only PDF visuals, arbitrary handwritten/image-only math, multi-column layout, DOCX true pagination, OCR language coverage, human map edition checking and production-scale performance need additional verification/hardening.
4. Production readiness additionally requires integration smoke tests on EC2/PostgreSQL/RQ/storage and genuine evaluation fixtures.

See `services/extraction/README.md`. Keep PR **draft** until owner runs local verification, integration gates are completed, and blockers are resolved.

### #10: agent/04-knowledge

- Target: `agent/01-platform`; base: `30c8c1f2a8aef9db45a1c29b79535546a28eac1e`; head: `859d1cfe758ca1fa49736cac2974b4b16a3b0830`.
- Status: draft; 13 changed files. Merge readiness: NOT VERIFIED.
- Local tests executed at initial audit: none. Reported author results below are historical, not acceptance evidence.

Implements #4 on top of Agent 1's unmerged foundation (PR #9). Stacked PR is intentionally based on agent/01-platform to avoid including unrelated foundation changes; retarget to main when Agent 1 merges.

### Shipped
- Tenant-scoped curriculum hierarchy, curriculum authoring/import, outcome mapping, provenance distinctions and explicit human approval.
- Source-aware text/visual/equation chunking and incremental indexing; model/dimension checks for 1536-vector embeddings.
- PostgreSQL full-text/keyword + optional semantic fusion, current resource-rights validation, deduplication and source diversity.
- Per-concept research planning, coverage/gaps, tentative conflict flags, exact source/page attribution, reusable research records and stale invalidation.
- Authenticated research/reindex outbox jobs through Redis/RQ, citation lookup, coverage, review and API endpoints.
- Additive SQL migration proposal for Agent 1 (no shared migration heads overwritten); synthetic data fixtures and tests.

### Integration gates / not yet verified
- Agent 1 must review and apply db/proposals/agent-04-knowledge.sql via Alembic, register services/curriculum/router.py and services/knowledge/router.py under /api/v1, regenerate OpenAPI, and arrange periodic outbox dispatch.
- Agent 2 must explicitly mark licensed/authorized uploads with provenance.access_approved, plus source_uri and license. Default is fail closed.
- Semantic mode requires SOMALOOM_EMBEDDINGS=openai and an OPENAI_API_KEY; only text-embedding-3-small (1536 dimensions) supported without migration.
- Tests committed but not executed in this connected environment; PostgreSQL/pgvector and Redis integration are unverified, and the synthetic relevance fixture is not evidence for real textbook accuracy.
- GitHub Actions have an account billing issue; no workflow was triggered or bypassed.

See services/knowledge/README.md for contracts and smoke commands. Do not merge until migration, tenant/FK/native PostgreSQL and RQ tests pass.

### #15: agent/05-ai

- Target: `main`; base: `cae10133377e2c184254e50fe7ca03a74ef0f493`; head: `8cddb786539b867978d057047e2ba0ea823cbd50`.
- Status: draft; 101 changed files. Merge readiness: NOT VERIFIED.
- Local tests executed at initial audit: none. Reported author results below are historical, not acceptance evidence.

## SomaLoom Agent 5 — guarded research-to-document AI

Closes no issue automatically: progress toward #5.

### Implemented on top of foundation PR #9
- Codex CLI constrained noninteractive provider adapter, runtime flag verification, isolated runner requirement, safe error classification, stdout/err limits, timeouts and concurrency controls.
- Independently authenticated JSON-schema API fallback; provider selection and usage counts.
- Per-outcome multi-source section generation and compilation; unknown citation removal, deduplication, source diversity, visual/equation references, unsupported material flags, coverage/quality report and teacher-review state.
- Tenant-owned RQ generation jobs, durable PostgreSQL queued records for redis redelivery, per-school active request quota, idempotency keys, cancellation, retries, structured version-1 document persistence.
- Authenticated `/api/v1/generations` create/status/cancel/retry/draft routes; registration in app composition.
- Mocked provider and tenant tests, controlled real-provider staging smoke harness and operator runbook `docs/AGENT_5_AI.md`.

### Integration dependency (important)
This branch was cut from `agent/01-platform` because the worker/auth/database contracts needed for generation exist in foundation PR #9 but not yet in `main`. Consequently, the PR currently shows **101 files vs main**, of which only **15 are Agent 5 changes** when compared against `agent/01-platform`. **Merge #9 first**; then refresh/rebase this PR so only Agent 5 files remain. Do not merge this PR independently of #9.

### Verification status / limitations
- Added `tests/test_generation.py` for schema-grounded section synthesis, invalid JSON, source-injection boundaries, unavailable CLI, fallback, HTTP authentication, idempotency and tenant isolation.
- **These tests have not run here**: connector-based repository editing does not give local checkout/Redis/Postgres/Codex runtime access. Run documented local `pytest`, `ruff`, compilation, PostgreSQL + RQ and sandbox smoke on staging.
- The required **real source-grounded Codex smoke generation is not yet demonstrated**. Real Codex CLI login, an approved isolated runner, real permitted evidence and independent token/key may be required.
- Current Agent 4 adapter treats topic IDs as learning-outcome UUIDs until a mapping is integrated; Agent 6/7 specifications and Agent 8 review/export will be integrated separately.
- Automatic recovery of orphaned running jobs, hardened Codex tool isolation, full production-use compliance, native database integration and deployment validation remain pre-release gates.
- GitHub Actions CI and staging workflows remain manual-only; not triggered due to account billing restriction.

### Reviewer requests
Agent 1: review single app registration and dependency/config changes.
Agent 4: confirm `EvidenceBundle` outcome, passages and visuals schema.
Agents 6/7: supply lesson/assessment-specific constraints.
Agent 8: consume `document_versions.body` for preview, teacher review and export.

**Do not enable unrestricted public generation or claim production readiness before these gates pass.**

### #11: agent/06-teaching

- Target: `main`; base: `cae10133377e2c184254e50fe7ca03a74ef0f493`; head: `3d6bd1cf0ba08f412001cb5c2b2bd52ae544f68f`.
- Status: open, non-draft; 11 changed files. Merge readiness: NOT VERIFIED.
- Local tests executed at initial audit: none. Reported author results below are historical, not acceptance evidence.

## Summary

Implements Agent 6's first functional teaching-document studio under `services/templates/teaching/**` and `services/validators/teaching/**`, against Agent 1's current core `GeneratedDocument` and Agent 5's `AIProvider` interface.

- Typed, editable `teaching.v1` specs, versioned templates and sections for **lesson notes**, **schemes of work**, **lesson plans** and **teacher guides**.
- Curriculum/outcome ID validation; source-linked evidence; prompt composition; a real asynchronous provider adapter returning the established `GeneratedDocument` envelope.
- Licensed-asset permission enforcement, native LaTeX/MathML blocks, and `visual_needed` placeholders.
- Coverage gaps, source/citation checks, duplicate/empty sections, basic arithmetic checks, duration and calendar/weekly allocation validation.
- AI output is forcibly marked `needs_review`; generated author/reviewer identities and revision numbers are discarded to prevent fake approval.
- Four-family tests, P5 mathematics equations/tables/visuals, sample science and 40-minute lesson plan, documentation and explicit local test record.
- No duplicate executor, assessment pipeline, frontend, export service or GitHub Actions/CI changes.

## Local verification

- **17 passed** (`PYTHONPATH=. python -m pytest -q tests/test_teaching_studio.py`) in an isolated working copy with minimal faithful Agent 1/5 contract shims.
- Python compilation and independent module import passed.
- Ruff unavailable locally; full repository E2E, live provider and external Agent 4/8 integrations not verified.
- Details in `services/templates/teaching/TEST_RESULTS.md`.

## Integration blockers / why draft

1. Agent 4 must supply real verified, tenant-scoped and curriculum version-scoped `EvidenceBundle`, including asset permission validation.
2. Agent 5 must configure and persist the production provider and generation job queue; wire authenticated job context into `TeachingStudio.generate`.
3. Agent 1 owns tenant authorization, API registration and durable storage. No unsecured teaching endpoint was introduced.
4. Agent 8 must implement UI editing, teacher approval and PDF/DOCX exports for `teaching.v1` blocks.
5. Verify full academic accuracy, source rights, international/Ugandan curriculum alignment and run integrated tests before release.

**Status:** implementation available for integration and review, **not** a claim that Issue #6's full production definition-of-done is met.

Refs #6

### #14: agent/07-assessments

- Target: `main`; base: `cae10133377e2c184254e50fe7ca03a74ef0f493`; head: `43181eeee96b1f6cc6832bca99bc18bfa833aff1`.
- Status: draft; 16 changed files. Merge readiness: NOT VERIFIED.
- Local tests executed at initial audit: none. Reported author results below are historical, not acceptance evidence.

Closes #7 after integration and acceptance verification.

## Delivered
- Strict Pydantic assessment blueprints, question-family schemas, licensed source provenance, reviewed visual references, MCQ/matching/numerical/rubric consistency.
- Tenant-scoped, immutable-version question bank with edit/review/approve/retire and duplicate fingerprints.
- FastAPI feature router under `/api/v1`: bank CRUD-style workflow, manual/automatic assembled exams, seedable variants, validation, teacher review/publication, private marking guide and allowlisted student paper.
- Deterministic mark/time/curriculum/coverage checks and safe AST arithmetic evaluation; answer-key and learner projection kept separate.
- Agent 5 provider-protocol candidate-drafting seam; no competing AI provider.
- PostgreSQL proposal in `db/proposals/agent-7-assessments.sql`, synthetic example question/spec/student/teacher JSON fixtures, and pytest coverage (exam, test, quiz, math, diagram, matching, duplicates, leakage, tenancy, denial).

## Integration blockers (non-claims)
- Agent 1 foundation currently lives on `agent/01-platform`, not `main`. The feature imports its `app.core`/auth/db modules. Register `services.assessment.router.router` in Agent 1's `app.main` and convert the migration proposal into the platform Alembic head after Agent 1 merges.
- Agent 4 evidence indexing, Agent 5 runtime job orchestration, Agent 3 visual verification, and Agent 8 PDF/DOCX exporter are independently owned; the API does not claim those integrated services are finished.
- GitHub Actions intentionally not used. The full test suite was authored but **not executed** in this session because Agent 1's runtime is not on the current base branch. Run `pytest tests/test_assessments.py -q` after foundation integration and document results before marking this PR ready for merge.

## Security
- API derives tenant only from authenticated school user; all bank/paper and linked asset/evidence lookups are school-filtered.
- Learner JSON does not serialize marking answers or matching pairs; marking guide has a separate staff-only endpoint.
- Only school admins/reviewers approve questions and publish assessments.


### #16: agent/08-web-publishing

- Target: `agent/01-platform`; base: `30c8c1f2a8aef9db45a1c29b79535546a28eac1e`; head: `eaecfa4c288a53b47548c7f359b4b88dc988f8ff`.
- Status: draft; 19 changed files. Merge readiness: NOT VERIFIED.
- Local tests executed at initial audit: none. Reported author results below are historical, not acceptance evidence.

## Agent 8 implementation — Issue #8 (draft, review required)

### Added on top of Agent 1 PR #9
- Responsive authenticated Next.js 16 publishing workspace: login, dashboard, settings, library, uploads, Telegram imports, authorized-site imports, processing jobs, curriculum/topic browsing, search/evidence, eight generation tiles, generated documents, question bank, structured editor, reviews and publishing.
- Real session-aware `/api/v1` requests: no simulated imported resources, jobs or generated output. Features without live owning-agent endpoints report errors rather than pretending success.
- Structured editor: edit text, LaTeX, table cells and captions; native browser MathML preview; school-scoped document version history and optimistic version saves; version-specific educator reviews and required verification attestations.
- Export: A4 PDF, editable DOCX, native OMML for supported LaTeX, teacher/student audience splitting, citations, school name, page numbers; fails closed on missing/unlicensed visual resolution.
- API: school-scoped document list, version reads/saves, approval/rejection, reviewed export and authenticated downloads; cross-school authorization and provenance verification. Only limited additive edits to Agent 1 `app.main` and API Dockerfile.
- New export dependencies, tests, and `docs/AGENT8_RELEASE.md` describing local checks and release gates.

### Blockers / not yet production complete
- Agent 2: upload, Telegram and website APIs must be verified in the integrated server.
- Agent 3: signed tenant-authorized image/diagram/map asset resolution. Publishing currently rejects visual assets rather than bypassing validation.
- Agent 4: verify curriculum/search response shapes and real evidence/license records.
- Agent 5: persist initial generated documents/versions, agree document body schema and section regeneration API.
- Agent 6/7: verify all six output families, marking guide formats and answer-key permissions end-to-end.
- Agent 1: review API router registration and Docker dependency additions; test full EC2/Nginx/HTTPS/durable storage + backup/restore.
- Remaining Agent 8 work: revision diff UX, printable asset embedding, richer equations beyond supported LaTeX subset, full browser/E2E walkthrough and screenshots.
- **No unit tests, npm builds, Docker smoke tests, real EC2 verification or rendered-file visual inspection were executed by this GitHub-connector session.** Tests are authored for local execution, not reported as passed.
- CI is paused due billing. No GitHub Actions rerun and no production deployment.

### Merge plan
PR targets `agent/01-platform` while its PR #9 remains open. After foundation merges, rebase/retarget and run the documented local verification commands before approval. Keep this PR in **draft** until acceptance; it does not close #8.

## Runtime baseline

Python 3.12.3; Node 18.19.1 (insufficient for Next 16); no Docker initially; venv unavailable initially. Installing isolated verification prerequisites. AWS instance-role STS succeeds. No production modifications or deployment performed.


## Reviewed feature file inventories

### PR #9 (feature-only against origin/main)

```text
.dockerignore
.env.example
.env.production.example
.github/workflows/ci.yml
.github/workflows/staging.yml
.gitignore
README.md
alembic.ini
apps/api/Dockerfile
apps/api/app/auth/__init__.py
apps/api/app/auth/router.py
apps/api/app/auth/security.py
apps/api/app/core/__init__.py
apps/api/app/core/config.py
apps/api/app/core/database.py
apps/api/app/core/models.py
apps/api/app/core/queue.py
apps/api/app/core/router.py
apps/api/app/core/schemas.py
apps/api/app/core/storage.py
apps/api/app/core/vector.py
apps/api/app/core/worker.py
apps/api/app/main.py
apps/web/Dockerfile
apps/web/next-env.d.ts
apps/web/next.config.ts
apps/web/package-lock.json
apps/web/package.json
apps/web/postcss.config.mjs
apps/web/src/app/globals.css
apps/web/src/app/layout.tsx
apps/web/src/app/page.tsx
apps/web/tsconfig.json
compose.yaml
contracts/v1/ContentBlock.schema.json
contracts/v1/CurriculumOutcome.schema.json
contracts/v1/Equation.schema.json
contracts/v1/ErrorResponse.schema.json
contracts/v1/EvidenceLink.schema.json
contracts/v1/Export.schema.json
contracts/v1/Extraction.schema.json
contracts/v1/GeneratedDocument.schema.json
contracts/v1/GenerationJob.schema.json
contracts/v1/Resource.schema.json
contracts/v1/ResourceVersion.schema.json
contracts/v1/VisualAsset.schema.json
contracts/v1/fixtures/content_block.json
contracts/v1/fixtures/curriculum_outcome.json
contracts/v1/fixtures/equation.json
contracts/v1/fixtures/evidence_link.json
contracts/v1/fixtures/export.json
contracts/v1/fixtures/extraction.json
contracts/v1/fixtures/generated_document.json
contracts/v1/fixtures/generation_job.json
contracts/v1/fixtures/resource.json
contracts/v1/fixtures/resource_version.json
contracts/v1/fixtures/visual_asset.json
contracts/v1/openapi.json
contracts/v1/schemas.py
db/migrations/env.py
db/migrations/script.py.mako
db/migrations/versions/0001_foundation.py
docs/AGENT_INTEGRATION.md
docs/ARCHITECTURE.md
docs/DEPLOYMENT.md
docs/VERIFICATION.md
infra/compose.production.yaml
infra/ec2/cloud-init.yaml
infra/nginx/nginx.conf
infra/postgres/init.sh
infra/systemd/somaloom-backup.service
infra/systemd/somaloom-backup.timer
requirements.lock
services/ai/provider.py
tests/conftest.py
tests/test_live_services.py
tests/test_platform.py
tools/backup.sh
tools/container_auth_smoke.py
tools/container_queue_smoke.py
tools/deploy.sh
tools/export_openapi.py
tools/generate_contracts.py
tools/generate_fixtures.py
tools/init_dev_env.py
tools/migrate.sh
tools/provision_admin.py
tools/restore.sh
tools/smoke.sh
```

Commit inventory:

```text
30c8c1f ci: pause automatic GitHub Actions checks while billing is blocked
7145953 fix(platform): preserve immutable resources and record verified launch gates
8f0c492 feat(platform): secure API, tenant schema, web login and EC2 foundation
```

### PR #13 (feature-only against origin/pr/9)

```text
db/proposals/agent-2-ingestion.sql
services/ingestion/README.md
services/ingestion/cli.py
services/ingestion/crawler.py
services/ingestion/dispatcher.py
services/ingestion/jobs.py
services/ingestion/library.py
services/ingestion/models.py
services/ingestion/requirements.txt
services/ingestion/router.py
tests/test_ingestion.py
```

Commit inventory:

```text
b3b3419 feat(ingestion): preserve alternate source provenance for deduplicated originals
280b940 fix(ingestion): honor robots.txt 404 allow and fail closed on service errors
da2595d perf(ingestion): paginate resource searches directly in SQL
45415b6 fix(ingestion): retry failed crawler URLs from durable checkpoints
4042f52 fix(ingestion): cancel at crawl checkpoint and recover stale queued work
a898002 feat(ingestion): add tenant-scoped Telegram history and bounded manual retry
a5d8d81 fix(ingestion): bounded Telegram rate-limit retries and sanitized transport failures
2b57418 fix(ingestion): return duplicate before charging school quota
1719d3f docs(ingestion): describe per-school storage limits
f6371f8 fix(ingestion): force safe download disposition for untrusted HTML resources
da72d81 feat(ingestion): enforce tenant storage quotas with transaction-scoped locks
fcbfa51 feat(ingestion): support deliberate re-crawl of previously visited pages
bec684e feat(ingestion): add bounded network backoff without bypassing URL safeguards
d94b351 style(ingestion): remove unused imports and normalize feature modules
d8bbfed style(ingestion): remove unused imports and normalize feature modules
949d1d0 style(ingestion): remove unused imports and normalize feature modules
ff7ab70 style(ingestion): remove unused imports and normalize feature modules
2068b26 style(ingestion): remove unused imports and normalize feature modules
4cadcc4 style(ingestion): remove unused imports and normalize feature modules
d2e6de6 fix(ingestion): repair Python formatting and browser CSRF test headers
a714076 fix(ingestion): repair Python formatting and browser CSRF test headers
5b04b1f docs(ingestion): document production scanner gating
b924e21 test(ingestion): avoid packaging-dependent test imports
7fe5b50 fix(ingestion): align migration proposal with retention-aware deduplication
311e848 fix(ingestion): lock per-tenant checksum to prevent concurrent duplicates
f79d1ae test(ingestion): validate upload, dedup, source isolation, webhook and SSRF defenses
fe4f7f5 fix(ingestion): refine import retry state
e8e3839 fix(ingestion): reject private website source hosts and enable manual version uploads
69cf261 fix(ingestion): version changed pages by canonical source URL
e783a5d fix(ingestion): avoid repeated scheduling of Telegram receipts
9af763c fix(ingestion): validate API imports against their authorized source
3eb643d fix(ingestion): enforce antivirus scanner before production ingest
5de39cf docs(ingestion): propose tenant-safe schema and integration guide
da80615 docs(ingestion): propose tenant-safe schema and integration guide
6f73c0d feat(ingestion): add resumable terminal importer and queue dispatcher
126f823 feat(ingestion): add resumable terminal importer and queue dispatcher
324a894 feat(ingestion): add resumable terminal importer and queue dispatcher
e5551e5 feat(ingestion): expose secure resources, sources and import endpoints
a030bf0 feat(ingestion): add RQ import workers and durable resource event outbox
1232018 feat(ingestion): pin DNS and enforce web authorization, robots and crawl budgets
7822c8c feat(ingestion): add feature tables and immutable tenant-scoped library
fb554d9 feat(ingestion): add feature tables and immutable tenant-scoped library
```

### PR #12 (feature-only against origin/pr/9)

```text
db/proposals/agent-3-extraction.sql
services/extraction/README.md
services/extraction/__init__.py
services/extraction/demo.py
services/extraction/engine.py
services/extraction/evaluation.py
services/extraction/jobs.py
services/extraction/models.py
services/extraction/requirements.txt
services/extraction/router.py
services/math/__init__.py
services/math/equations.py
services/math/omml.py
services/visuals/__init__.py
services/visuals/classify.py
tests/fixtures/extraction/ground_truth.example.json
tests/test_extraction_db.py
tests/test_extraction_engine.py
tests/test_extraction_evaluation.py
```

Commit inventory:

```text
9a725e8 fix(extraction): enforce tenant-composite FKs in proposed outbox
4b2ab6f test(extraction): cover real TeX fraction and adjacent DOCX captions
ddc710c fix(demo): render escaped f-string braces as genuine TeX fraction
e981a48 feat(extraction): validate math rendering and link adjacent DOCX captions
8c1f61b fix(extraction): preserve HTML source links and propagate worker failures
3762d13 feat(extraction): propagate source URI into each block reference
0c11b48 feat(extraction): attach immutable source URI and bound DOCX decompression
023f40f test(extraction): assert hierarchical semantic context
15ce655 fix(demo): preserve TeX fraction backslashes
b573618 feat(extraction): heading hierarchy and OCR image size bounds
f6b94c6 feat(extraction): bounded RQ retries and page-progress updates
ddfb5af feat(extraction): retain original equation crops and observed visual labels
25686e7 test(extraction): add mixed textbook demo, fixtures, measured evaluation and integration runbook
bc7a041 chore: remove unused worker imports
8d2a4d4 fix: repair PDF captions and avoid misleading DOCX/HTML associations
b45f4bf feat(extraction): integrate tenant-isolated RQ jobs, object storage and API adapters
c87ae14 feat(extraction): implement bounded PDF/OCR/DOCX/HTML parsers and OMML equations
fd2c179 feat(extraction): define provenance-rich blocks, safe equation normalization and visual classifiers
```

### PR #10 (feature-only against origin/pr/9)

```text
db/proposals/agent-04-knowledge.sql
services/curriculum/__init__.py
services/curriculum/models.py
services/curriculum/router.py
services/knowledge/README.md
services/knowledge/embeddings.py
services/knowledge/indexer.py
services/knowledge/models.py
services/knowledge/research.py
services/knowledge/retrieval.py
services/knowledge/router.py
tests/fixtures/agent04_relevance.json
tests/test_agent04.py
```

Commit inventory:

```text
859d1cf fix(agent-04): normalize whitespace correctly during citation verification
00a1fd9 fix(agent-04): verify evidence against live extracted sources and reject stale bundles
2381f82 fix(agent-04): version-aware attribution, stale research and synthetic retrieval evaluation
285f547 feat(agent-04): authorized curriculum import and semantic API wiring; harden provenance invalidation
0e0a860 feat(agent-04): curriculum mapping, rights-scoped hybrid retrieval and research bundles
```

### PR #15 (feature-only against origin/pr/9)

```text
apps/api/app/main.py
apps/api/app/routes/__init__.py
apps/api/app/routes/generation.py
docs/AGENT_5_AI.md
pyproject.toml
requirements.lock
services/ai/provider.py
services/generation/__init__.py
services/generation/dispatch.py
services/generation/orchestrator.py
services/generation/repository.py
services/generation/schema.py
services/generation/smoke.py
services/generation/tasks.py
tests/test_generation.py
```

Commit inventory:

```text
8cddb78 docs(ai): rights-based evidence selection, visuals and verified cancellation locks
4d44522 fix(ai): serialize generation completion with cancellation
eebfc05 fix(ai): fail-closed production provider readiness
5fd7db9 feat(ai): tenant-safe licensed visual asset retrieval tied to evidence pages
9c79d76 feat(ai): include validated visual evidence and preserve mapped references
d7adabd feat(ai): typed source-linked diagram and map references
2b9c6b0 fix(ai): refuse evidence without declared source rights
b7792d9 feat(ai): document-family guidance and minimum assessment format checks
a1928ea fix(ai): define source diversification and arithmetic check helpers
9f27b6c feat(ai): diversify evidence sources and independently check simple arithmetic
acf2538 test(ai): declare async pytest dependency and clean smoke harness
3ae615a test(ai): declare async pytest dependency and clean smoke harness
ce368bf test(ai): declare async pytest dependency and clean smoke harness
b1730be test(ai): controlled real-provider smoke harness with externally supplied evidence
43a8c06 feat(ai): report tenant generation quota with HTTP 429
01f9282 feat(ai): per-tenant active generation quotas with serialized submissions
23cf76e fix(ai): allow bounded large multi-section generation jobs
80b1176 fix(ai): fail-closed queue retries and restrict teacher mutation to owner
f977580 fix(ai): enforce production runner gate and teacher ownership
950ca78 fix(ai): enforce production runner gate and teacher ownership
dc5af71 fix(ai): enforce production runner gate and teacher ownership
8a52093 fix(ai): enforce production runner gate and teacher ownership
6d7f668 docs(ai): runtime isolation, integration contracts, limits and local verification
539fbc8 docs(ai): runtime isolation, integration contracts, limits and local verification
0b01cca test(ai): source grounding, injection, provider failures, tenant isolation and idempotency
dc976d4 fix(ai): register routes and tighten checks
3e1a9a1 fix(ai): register routes and tighten checks
28f6b39 fix(ai): register routes and tighten checks
dc94fdb fix(ai): register routes and tighten checks
923f7d5 fix(ai): register routes and tighten checks
8e9282c feat(ai): durable RQ generation worker and tenant-scoped generation API
65f5cfe feat(ai): durable RQ generation worker and tenant-scoped generation API
a68a0e7 feat(ai): durable RQ generation worker and tenant-scoped generation API
5836b8b feat(ai): tenant-safe evidence lookup and document persistence
511020a feat(ai): multi-source bounded synthesis and deterministic citation/coverage validation
e2826d3 feat(ai): add typed generation contracts
ce6ad67 feat(ai): add typed generation contracts
0ce130d feat(ai): secure bounded Codex and API provider adapters
```

### PR #11 (feature-only against origin/main)

```text
fixtures/README.md
services/templates/teaching/README.md
services/templates/teaching/TEST_RESULTS.md
services/templates/teaching/__init__.py
services/templates/teaching/schemas.py
services/templates/teaching/service.py
services/templates/teaching/templates.py
services/validators/__init__.py
services/validators/teaching/__init__.py
services/validators/teaching/validation.py
tests/test_teaching_studio.py
```

Commit inventory:

```text
3d6bd1c docs(teaching): record isolated local QA outcomes and remaining integration
4dc12be fix(teaching): enforce human review and licensed visual permission
bcbef34 fix(teaching): enforce human review and licensed visual permission
b34d4b0 fix(teaching): enforce human review and licensed visual permission
8a6929b fix(teaching): enforce human review and licensed visual permission
9f39528 test(teaching): exercise generation adapter for all four types
83eeff9 feat(teaching): add typed four-family teaching generation studio and validators
```

### PR #14 (feature-only against origin/main)

```text
db/proposals/agent-7-assessments.sql
services/assessment/README.md
services/assessment/ai_drafts.py
services/assessment/documents.py
services/assessment/generation.py
services/assessment/models.py
services/assessment/router.py
services/assessment/schemas.py
services/assessment/validation.py
services/templates/assessment/EXAMPLE.md
services/templates/assessment/fixtures/diagram_question.json
services/templates/assessment/fixtures/numerical_question.json
services/templates/assessment/fixtures/student_paper_example.json
services/templates/assessment/fixtures/teacher_guide_example.json
services/templates/assessment/fixtures/test_spec.json
tests/test_assessments.py
```

Commit inventory:

```text
43181ee test(assessment): add synthetic fixtures and tenant-scoped visual checks
a644561 feat(assessment): add tenant-scoped exam studio and question bank (#7)
```

### PR #16 (feature-only against origin/pr/9)

```text
apps/api/Dockerfile
apps/api/app/main.py
apps/web/src/app/[section]/page.tsx
apps/web/src/app/globals.css
apps/web/src/app/layout.tsx
apps/web/src/app/page.tsx
apps/web/src/components/math-equation.tsx
apps/web/src/components/studio-app.tsx
apps/web/src/lib/studio.ts
docs/AGENT8_RELEASE.md
services/export/README.md
services/export/publishing.py
services/export/requirements.txt
services/export/router.py
services/rendering/document.py
services/rendering/omml.py
tests/test_agent8_export_api.py
tests/test_agent8_publishing.py
tests/test_agent8_workflow.py
```

Commit inventory:

```text
eaecfa4 feat(agent8): editable math and tables, school-branded exports and provenance checks
8e0049b feat(agent8): persist document revisions, reviewer attestations and integrated publishing workflow
8500e4b feat(agent8): add tenant-scoped reviewed export API, downloads, authorization tests and image dependencies
a006422 feat(agent8): authenticated publishing studio, MathML preview and guarded PDF/DOCX exporters
```

## Executed baseline and integration checks

- Foundation: SQLite 16 passed, 2 skipped; native PostgreSQL/Redis 18 passed. Ruff and formatting passed; fresh upgrade/downgrade/upgrade passed.
- Initial feature tests: ingestion 8 passed; extraction 13 passed; AI 7 passed; teaching 17 passed. Knowledge initially 2 failed / 7 passed; assessments initially 1 failed / 3 passed / 8 fixture errors. Fixed UUID string coercion, Origin test headers, test-only registration, malformed marks fixture and FastAPI lazy-router incompatibility.
- Combined initial run: 97 passed / 2 failed / 2 skipped; failures missing PDF libraries. Installed required Cairo/build libraries and pypdf; image contains OCR, publishing and scanner dependencies.
- First native combined run: 99 passed / 2 failed; PostgreSQL lexical recall and hardcoded migration head assertion fixed.
- Native combined: 101 passed. New stream/RQ/six-family suite: 7 passed. Reproducible isolated native script: 108 passed, no skips; Alembic check clean; populated rollback and fresh upgrade/downgrade passed.
- One concurrent shared-database run was invalidated by a migration drill (107 passed / 1 failed, UndefinedTable); it is not a code regression or acceptance result. tools/verify_integration.sh prevents this by creating isolated containers and sequencing tests and drills.
- Next.js TypeScript initially failed on missing MathML JSX definitions; fixed. Production build and TypeScript passed using isolated Node 22.
- Python audit initially 51 findings in Pillow/pip/pytest; upgraded Pillow 13, pip 26.2.2, pytest 9.1.1. Re-audit: no known vulnerabilities. npm audit: zero vulnerabilities.
- History secret scan covers original PR ancestry. Two findings were exactly the synthetic object key synthetic/diagram in Agent 4 tests, not credentials. Exact-value allowlist added; scan then passed.

## Conflicts and security decisions

Only Git merge conflict: apps/api/app/main.py registering generation vs publishing; preserved both and added all reviewed feature routers. Feature migrations use one immutable additive revision, not mutable create_all at startup. Corrected duplicate unique-constraint names in assessment models and distinct pgvector/GIN index names. Extraction outbox/receipts adapted from Agent 3 proposal into central metadata and migration.

Critical functional seams repaired: Redis event_type contract and actual consumer; checksum/tenant/event verification; transactional extraction intent; common EBS/S3 store; text/plain support and preservation of HTML originals; automatic index handoff; permission-aware topic/outcome mapping; canonical blocks; six-family queue routing; draft/version envelope; real source-management payloads; PATCH/PUT/DELETE CORS; reviewed visual resolution; student answer filtering; stale-evidence checks; document save serialization.

Merge readiness: integration is reviewable but release acceptance remains gated by real AI, Telegram, genuine official curriculum/educator acceptance, DNS/public TLS and cloud restore verification. No original feature PR is marked accepted solely from authored tests. Main and all agent branches remain untouched.

## Final verification and disposition

110 isolated native tests passed, schema drift clean, populated/fresh migration drills passed. Added durable export_requests revision a7ddca613219 and real RQ exports. Regenerated OpenAPI from the integrated app: 70 paths. Real Tesseract, visually inspected five-page PDF and native OMML DOCX, live private EC2 browser (including zero serious/critical axe findings), actual owned-site CLI, five-source RQ research and encrypted off-instance restore passed. Relevant coordination issue comments and all eight PR review-thread lists rechecked; no unresolved threads returned.

Staging faults found and repaired: nonsecret ClamAV definitions unreadable due bootstrap umask; Nginx upstream DNS stale after API container recreation; two insufficient UI text contrast colors. A repeated browser save initially failed because the test filled the exact existing text (no change event); test now uses a unique revision. Owned test robots initially skipped pages conservatively due stdlib first-match behavior; fixture rules reordered without weakening production SSRF/authorization.

Original PRs/main remain unchanged. Direct git push is unavailable because this shell has no GitHub credential helper; publication uses the authorized GitHub connector. Remote release commit will preserve each original PR head as ancestry, with an identical reviewed file tree; local detailed integration history is retained separately. No force push or history deletion.

Final hardening retains the authenticated teacher as research requester, validates selected class/subject against the topic catalogue, and serializes extraction claims before OCR. Native workflows now verify the requesting-teacher attribution and reject incorrect curriculum context.

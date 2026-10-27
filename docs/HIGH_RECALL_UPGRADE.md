# High-recall research / resource coverage upgrade

Scope: feature branch fix/knowledge-coverage-recall built on deploy/notesug-codex.
Safety: No live database mutation, no EC2 deployment, no GitHub Actions triggers.
Benchmark integrity: Code audit and new synthetic tests only. **Real P7 SST accuracy, Recall@50, EC2 and textbook metrics are NOT independently verified.**

## Baseline from inspected source code

| Behavior | Before | Feature branch |
|---|---|---|
| Research query | One literal concept | Up to five bounded deterministic contextual/alias variants |
| Retrieval scope | Grade+subject, broad fallback only if zero | Targeted and tenant/rights-broadened on every first-pass query |
| Research per-query K | 8 | Up to 24 |
| Chunks from one book | Hard cap 3 | Configurable to 8 for research; standalone search retains default 3 |
| Cross-book evidence | Top-ranked search | Repeated-hit dedup and per-source round robin, max 40 per concept |
| Weak results | No second pass when any hit exists | Bounded second pass for fewer than two distinct sources |
| Research query budget | No explicit total bound | 120/topic by default; SOMALOOM_RESEARCH_MAX_QUERIES bounded 12..200 and deferred concepts reported |
| Audit | No per-concept query record | Query variants, scope, counts, source diversity, budget and gaps |
| Searchability | Upload/archive confused with searchable | Admin-only current-version scan/index/rights/embedding/failure inventory |
| Visuals in teaching generation | Indexed but not forwarded | Verified permission-approved maps/diagrams carried to teaching AI and saved metadata |
| Source titles | Curriculum topic name used as citation title | Original resource title retained when available |
| Generation prompt evidence | Potentially unbounded per topic | Bounded to 80 selected excerpts total, six per outcome, preserving first pass across outcomes |

These are **configuration/code deltas, not measured accuracy improvements**.

## Security and provenance invariants

- All searches retain tenant and source-rights predicates in retrieval.query_base.
- Exact, current, permission-approved source/page checks remain mandatory.
- AI text citations still require legitimate content-block references. Visual asset IDs are separate from text citation IDs.
- Low-confidence OCR, unlicensed diagrams, deleted/superseded resources, and rights-pending sources cannot become authoritative search evidence.
- Telegram archive-only oversized originals are NOT ingested by this change; malware scanner, size limits, consent and source permissions must not be bypassed.
- Teacher review is still required, and model/schema validation does not establish academic accuracy.

## API and frontend

- Admin-only: GET /api/v1/knowledge/resource-coverage?page=1&page_size=25 returns paginated resource searchability facts.
- Reference library: school administrator panel shows search status and missing reasons and allows per-version reindex.
- GET /api/v1/topics/{topic_id}/coverage adds search_audit.
- Existing single-resource-version reindex API remains unchanged; no mass reindex or automatic production migration is activated.

Archive-only Telegram totals live outside the resource database and are reported as unknown, not zero. Current tables also do not give a reliable complete per-page OCR failure count; normalized extraction output and archive telemetry must be reconciled separately.

## Verification commands

From the feature branch on a development machine with installed dependencies:

    python -m compileall -q services/knowledge services/generation services/templates/teaching services/validators/teaching apps/api/app
    pytest -q tests/test_high_recall.py tests/test_agent04.py tests/test_generation.py tests/test_generation_selection.py tests/test_master_integration.py
    ruff check services/knowledge services/generation services/templates/teaching services/validators/teaching apps/api/app tests/test_high_recall.py
    cd apps/web && npm ci && npm run typecheck && npm run build

Run integration tests against a disposable PostgreSQL/pgvector instance and Redis. Never aim TEST_DATABASE_URL or TEST_REDIS_URL at a production school service.

The existing relevance fixture is synthetic P5 Science; new tests add synthetic P7 SST synonyms, per-resource limits, metadata gaps, tenant scope, and visual-prompt evidence. No human-annotated real-book dataset is available here, so real Recall@50 and latency/price metrics cannot be claimed.

## Outstanding acceptance work

1. Run all unit, integration and production web build commands locally or on disposable EC2; fix actual failures.
2. Create a permitted, manually labeled P7 SST reference set, including scans, maps and alternative wording. Measure baseline and new Recall@50 with exactly the same labels, plus latency and cost. Aim for >=90% Recall@50 but report observed numbers.
3. Verify licensed map rendering end-to-end. The base editor can show a placeholder for a missing/resolved image URL. Carrying an asset ID into an AI prompt does **not** yet prove that a PDF or DOCX will display the map correctly.
4. Reconcile actual archive counts, OCR warnings, and unprocessed source versions using live read-only diagnostics.
5. Profile extended queries; tune bounds when using vector embeddings with per-call vendor cost.
6. Review PR, deploy on an isolated staging instance, test and prepare a reversible production rollout.

**Status:** Code change submitted for review; not deployed, and P7 SST real-source acceptance still pending.

# Agent 4 — Curriculum and Knowledge Service

Feature branch: `agent/04-knowledge`; foundation: Agent 1 `agent/01-platform`.

## Integrate (Agent 1)
1. Review `db/proposals/agent-04-knowledge.sql` and integrate via a **new Alembic revision**, never edit the foundation migration. Apply it in deployment before enabling these routers. Add reverse migration and validate PostgreSQL composite tenant FKs and HNSW.
2. In `apps/api/app/main.py`, after core imports: `from services.curriculum.router import router as curriculum_router` and `from services.knowledge.router import router as knowledge_router`; include both with `app.include_router(..., prefix="/api/v1")`.
3. Generate shared OpenAPI after registration; Agent 1 owns central schema and app registration. No GitHub Actions invocation needed while billing prevents runners.
4. Register trusted RQ workers for `services.knowledge.research.run_job` and run a periodic dispatcher that calls `dispatch_pending(SessionLocal())`; startup is **not** allowed to auto-create tables. Ensure source-rights approval is written during Agent 2 ingest.

## Source contract (Agent 2/3)
Each `resources.provenance` MUST contain `{"source_uri":"...","license":"...","access_approved":true}` before it is indexed. The default is deny. Optional `grade`, `subject`, `curriculum_id`, and `reliability` drive filters. The importer may grant `access_approved` only after authorization is verified by an administrator. Blocks use their recorded 1-based page, figures use captions and page, equations use LaTeX and page. All three remain FK-linked to the original extraction and resource version.

Index work is idempotent per resource-version/source/chunk. Changed or removed chunks invalidate records using that version. Approved research is reusable until marked stale. Research bundles contain references to existing indexed sources, not hallucinated citations.

## Embeddings
Existing foundation uses `vector(1536)`. Only `text-embedding-3-small` with explicitly requested **1536** dimensions is supported. Set `SOMALOOM_EMBEDDINGS=openai` and `OPENAI_API_KEY` on the EC2 worker to enable semantic indexing and research. Without these, keyword search works but similarity search is **not** enabled; API search enables semantic ranking when those same environment variables are present; otherwise it truthfully reports keyword-only. Never load Codex CLI user credentials into the server. Query/vector model changes require a coordinated schema migration and full reindex.

## Routes
`POST /api/v1/curricula`, `POST /api/v1/curricula/import`, `GET /api/v1/curricula`, `GET /api/v1/curricula/{id}/topics`, `GET /api/v1/topics/{id}/outcomes`, `POST /api/v1/curricula/{id}/topics`, `POST /api/v1/topics/{id}/outcomes`, `POST /api/v1/topics/{topic_id}/mappings/{id}/review`.

`POST /api/v1/search` accepts `{query, topic_id?, tenant_id?, filters?, k?}`. The optional tenant_id is checked against the session; it cannot change the tenant scope. Filters: grade, subject, curriculum_id, source_kind, resource_ids. Returns real quotes, exact resource-version/source block and page, license and URI. No results means missing evidence.

`POST /api/v1/research/jobs` with `{topic_id}` produces a durable outbox + RQ job; `GET /api/v1/research/jobs/{id}` polls status; `GET /api/v1/research/bundles/{record_id}` returns structured evidence for Agent 5; `GET /api/v1/topics/{topic_id}/coverage` reports gaps/conflicts. `POST /api/v1/research/bundles/{id}/review` approves or rejects with optional `conflicts_acknowledged`. `POST /api/v1/index/resource-versions/{id}` queues an index rebuild. `GET /api/v1/citations/{id}` validates evidence access at lookup time. `POST /api/v1/research/dispatch` permits manual outbox recovery by an administrator.

The source and curriculum import APIs accept **only administrator-entered or authorized material**. A proposed official outcome becomes official only when a reviewer approves it with its source/license; generated suggestions remain enrichment.

## Verification
Run `pytest -q tests/test_agent04.py` and `ruff check services/curriculum services/knowledge tests/test_agent04.py`. A real PostgreSQL 16 + pgvector test is needed to verify GIN/HNSW, lexical SQL, and cross-tenant source joins, plus an RQ worker integration test. Synthetic fixtures prove interfaces only, not textbook relevance or production safety. No CI checks should be triggered solely to bypass the account billing problem.

## Known limitations
- Service and migrations require Agent 1 integration.
- Search API does not currently call the embedding provider; separate research worker uses embeddings when configured.
- Conflict heuristics only raise provisional review flags. They do not prove the claims truly contradict.
- Source provenance depends on approval performed by the ingestion authority; approved license metadata is not a legal rights determination.
- Relevance evaluation fixtures are synthetic and are not a real multi-textbook gold-standard benchmark.

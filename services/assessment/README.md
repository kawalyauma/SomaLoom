# SomaLoom Assessment Studio — Agent 7

This implementation owns structured exams, topic/class tests, quizzes, worksheets,
assignments and revision exercises; approved/versioned question bank; deterministic
assembly; quality review; separate learner-facing and teacher-only document projections.
It does **not** implement a competing model provider, curriculum index or PDF exporter.

## Agent 1 integration

Merge Agent 1 platform first (currently on `agent/01-platform`). Then import the
feature tables **before migrations/tests create metadata** and register its router in
`apps/api/app/main.py`:

    from services.assessment.router import router as assessment_router
    app.include_router(assessment_router, prefix="/api/v1")

Agent 1 should convert `db/proposals/agent-7-assessments.sql` to an Alembic revision
after migration 0001; Agent 7 does not modify the platform migration head.
The feature uses `app.auth.security.require_roles`, `app.core.database.get_db`,
`app.auth.router.audit`, and the versioned `contracts.v1.schemas.Page`.
All database reads/writes include the school tenant derived from the authenticated
user. Platform admins without a school identity cannot use school-specific endpoints
without an approved, explicit delegated tenant context.

## API guide

Authenticated school-scoped routes, all under `/api/v1`:

- `POST /question-bank`: create a draft question with marking details.
- `GET /question-bank`: paginate/filter current revisions by subject, topic,
  difficulty and approval status. Response **omits** marking answers.
- `GET /question-bank/{question_id}`: current public question.
- `GET /question-bank/{question_id}/versions`: immutable revision metadata.
- `GET /question-bank/{question_id}/marking-answer`: teacher-only detail.
- `POST /question-bank/{question_id}/revisions`: full new draft revision.
- `POST /question-bank/{question_id}/approve`: reviewer/admin approval.
- `POST /question-bank/{question_id}/retire`: retire all revisions.
- `POST /assessments`: assemble selected approved question revision IDs.
- `POST /assessments/generate`: automatically assemble from approved bank;
  `variant_seed` creates alternate deterministic variants when inventory permits.
- `GET /assessments`, `GET /assessments/{id}`: school-scoped listings and previews.
- `GET /assessments/{id}/student-paper`: **allowlisted** A4 document for Agent 8.
- `GET /assessments/{id}/marking-guide`: separate staff-only document.
- `GET /assessments/{id}/validate`: errors, duration and coverage warnings.
- `POST /assessments/{id}/publish`: school admin/reviewer approval only.

`school_admin`, `teacher`, `reviewer` can read; teachers and school admins
create/revise; school admins and reviewers alone may approve/publish. A public learner
route has **not** been created. Editors/exporters must use the student projection
for learner PDFs and NEVER serialize database `sections` or `payload` directly.
Export permission for teacher guides must also be enforced by Agent 8.

## AI, evidence, verification

`ai_drafts.draft_candidates(provider, spec, evidence, model=...)` integrates with
Agent 5's `AIProvider` protocol and Agent 4's licensed evidence results. It returns
**unapproved** candidates for human editing. It never executes untrusted source text,
scrapes sources, or introduces a second provider. Until Agent 5's registered runtime,
job orchestration and Agent 4 retrieval have merged, AI drafting is an integration
seam rather than a production job endpoint. Bank assembly itself is functional.

`QuestionDraft` checks option identity, matching pairs, diagram verification status,
answer presence, rubric/step totals and referenced-source license metadata.
Arithmetic expressions use a safe AST evaluator, not Python `eval`. Complex
symbolic equivalence, source-fidelity checks and true diagram geometry validation
require Agent 3/4 integration; visuals lacking a verification flag are rejected.
Percentages are mark-weighted and deviations generate teacher-visible warnings.

`AssemblyRequest` includes `spec`, `question_revision_ids` (manual mode) and
`variant_seed` (automatic mode). `AssessmentSpec` includes curriculum, grade,
subject, topic/outcome IDs, type, term, duration, total marks, question counts,
section specs, difficulty percentages, topic percentages, instructions and school
branding. Exact mark and question totals and estimated duration are checked before
saving and again before publishing. Paper creation is synchronous; larger AI jobs
must be submitted through Agent 5's persisted outbox/RQ pipeline.

## Local verification and deployment

After Agent 1 merges:

    pip install -e '.[dev]'
    pytest tests/test_assessments.py -q

For live PostgreSQL, set `TEST_DATABASE_URL` to an isolated test database.
Tests use Agent 1's authenticated `client`, `accounts` and SQLite fixture,
and do not invoke GitHub Actions. Apply the Agent 7 migration through Agent 1's
migrations before starting the API. Do not expose student previews as unauthenticated
public endpoints. Export A4 layouts, images, maps, graph fidelity and mathematical
typesetting remain with Agent 8 and Agent 3, respectively.

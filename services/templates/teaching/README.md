# SomaLoom Teaching Studio (`teaching.v1`)

**Owner:** Agent 6. Distinct output families: `lesson_notes`, `scheme_of_work`, `lesson_plan`, and `teacher_guide`.

## Runtime integration

Agent 4 supplies an authorized, verified `EvidenceBundle` whose curriculum ID/version, level, subject, topic and outcome IDs exactly match `TeachingSpec`. Evidence retains source URI, license, page and any licensed visual asset ID. Missing/unsupported curriculum mappings fail closed; no invented curriculum standards.

Agent 5 injects its configured `AIProvider` (see `services/ai/provider.py`). The authenticated application first creates a persisted tenant-bound `GenerationJob` before invoking the studio:

```python
result = await TeachingStudio(provider, model="configured-model").generate(
    spec=spec, evidence=verified_bundle,
    tenant_id=authorized_tenant_id, generation_job_id=persisted_job_id,
)
# result.document matches contracts.v1.schemas.GeneratedDocument
# result.validation contains gate failures and teacher-review recommendations
```

**Security:** `tenant_id` and `generation_job_id` must originate in authenticated job context, not untrusted request headers/body. Agent 4 and the worker must verify the tenant owns every evidence item. The adapter does not have storage access and cannot enforce cross-tenant isolation by itself. Do not mount an unauthenticated public generation endpoint. Queue orchestration and endpoint registration belong to Agents 1/5. Never publish a document with `validation.valid=False`. All generated outputs need human educator approval, even when the automated gates pass.

## Agent 8 editable/export contract

`GeneratedDocument.body` contains `schema_version="teaching.v1"`; ordered `sections` with stable UUID IDs, keys, titles, outcome IDs and typed editable `blocks`; `scheme_weeks`; `lesson_stages`; document title, review status, author/reviewer IDs and revision; `spec`; `quality`; `provider`; and `reference_index`.

Block kinds include paragraphs, headings, activities, questions, tables (`rows`), equations (`latex` or `mathml`), visuals (`asset_id`), and pending original diagrams (`visual_needed`, `visual_instruction`). Use a true LaTeX/MathML renderer and resolve asset IDs through Agent 3's licensed asset store. Never invent illustrations or rasterize equations. Preserve citations, UUID IDs, period allocations and approval metadata during editing and export. Agent 8 owns PDF/DOCX, the final editor, and immutable approval history, not this component.

## Automated checks / limitations

Versioned required section keys are in `templates.py`. Quality gates check citation/outcome relationships, gaps, duplicate blocks and repeated text, licensed visuals, required visual placeholders, basic numeric arithmetic, exact lesson-stage time, week capacity, excluded teaching days and mandatory sections. These checks cannot prove science correctness, general symbolic math, pedagogical suitability or licensing by themselves; factual claims still need teacher review. Country defaults to Uganda, but teacher-supplied curricula are supported internationally and no official national syllabus is hardcoded.

## Tests

Run locally with `python -m pytest -q tests/test_teaching_studio.py` and `ruff check services/templates/teaching services/validators/teaching tests/test_teaching_studio.py`. The tests use a fake AI provider and fictional teacher-supplied outcome data. No GitHub Actions workflows were added/changed due to the project's billing constraints. Real Agent 4/5/E2E/Agent 8 integration remains an integration task.

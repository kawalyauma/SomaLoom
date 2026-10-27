# Automatic master schemes

Teaching scheme PDFs and DOCX files are detected from their filenames or the upload form's “Scheme of work” purpose. Marking schemes are excluded. The dedicated planning worker extracts source text, asks the configured AI provider for all scheduled rows, validates class/subject identity and exact block quotations, and merges the results into one master per school, class and subject.

The generation form selects class → subject → term → teaching week → optional lesson. It sends these values to `/api/v1/generations/for-class`; the server resolves the source schedule, curriculum, topics and outcomes. The generated resource receives the selected lesson objectives and real scheme evidence. Users never select a curriculum.

`/master-schemes` displays the full schedule, source page and quotation, processing status and source variations. Missing terms/weeks are retained as gaps. Lesson allocations inferred from source subtopics are labelled. Where sources disagree, the newest uploaded source wins and alternatives remain visible. Replaced/deleted sources stop being selectable immediately. These are uploaded scheme planning targets, not an assertion of official curriculum endorsement.

## Operations

Deploy all normal compose overlays, including `infra/compose.codex.yaml`, which defines `planning-worker`. Run the additive Alembic migration before starting it. The worker prioritizes the `generations` queue, then the `schemes` queue; the archive worker continues processing bulk downloads independently. Discovery runs every 30 seconds and caches successful AI chunks. Failed source jobs can be retried twice from the page. New sources are imported in bounded discovery batches. Check logs for sanitized failure types, and inspect source extraction quality if rows need classification.

New tables: `scheme_imports`, `master_schemes`. Parser entry point: `services.schemes.tasks`. Merge, invalidation and citation lookup: `services.schemes.service`. Tenant-scoped API: `services.schemes.router`.

Coverage depends on the source PDFs actually present. Upload missing class/subject/term schemes to extend the master automatically. There is no generated fallback schedule for missing source material.

Validation: production Next.js build; API build; tests `test_generation_selection.py` and `test_master_schemes.py` cover tenant isolation, schedule selection, replacement invalidation and exact source identity/quotes.

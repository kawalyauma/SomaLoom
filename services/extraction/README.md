# Agent 3 — Multimodal Document Intelligence

Agent 3 implements a bounded source-fidelity extraction engine. It does not
generate new geography, mathematical meaning, or guessed diagram labels.

## Supported input and output

- Native PDF: page/rectangle text positions, heading heuristics, visual bytes,
  selected caption linkages, and PyMuPDF-detected tables.
- Scanned PDF and image: Tesseract OCR with per-line confidence and page/box;
  review flags for uncertain transcriptions. OCR is optional at runtime, never
  claimed when Tesseract is not installed.
- DOCX: original ordered paragraphs and table cells, inline images, supported
  OMML equations. **DOCX page numbers cannot be known without a layout engine**
  and are represented as page 1 with the `page_unknown` metadata flag.
- HTML: headings, lists, embedded images, tables and MathML TeX annotations.
  External image URLs are **not fetched** (SSRF protection). HTML has no
  stable page rectangles.

`ExtractedDocument` contains stable block IDs, ordered content, original
page/bbox, confidence, editable LaTeX where reliably recoverable, original
asset object keys and checksums, license, source/version IDs, warning and
partial flags. Use `semantic_sections(document)` for Agent 4.

Print fidelity: original embedded visual bytes are retained. A low-resolution
warning is emitted for small assets; **240–300 dpi printable quality is not
guaranteed** by a low-resolution original. Maps always require boundary/edition
verification. Vector-only PDF illustrations and arbitrary image-based equations
are still human-review cases.

## Install / run locally

From the repository root on Python 3.12+, with the foundation dependencies:

```sh
python -m pip install -e '.[dev]'
python -m pip install -r services/extraction/requirements.txt
sudo apt-get install tesseract-ocr  # install language packs as required
pytest -q tests/test_extraction_engine.py tests/test_extraction_db.py tests/test_extraction_evaluation.py
python -m services.extraction.demo --output /tmp/somaloom-demo
python -m services.extraction.evaluation tests/fixtures/extraction/ground_truth.example.json
```

The demo writes a synthetic *textbook passage* with an explanation, a diagram,
a table and editable structured LaTeX. No copyrighted textbook figures are bundled.

## Service integration contract

Agent 1's FastAPI composition owner registers:
```python
from services.extraction.router import router as extraction_router
app.include_router(extraction_router, prefix="/api/v1")
```

API (requires authenticated school-scoped user):
- `POST /api/v1/extractions` accepts `{"resource_version_id":"UUID"}`.
- `GET /api/v1/extractions/{id}` retrieves status.
- `GET /api/v1/extractions/{id}/document` returns normalized structured JSON.

Agent 2 emits trusted `resource.available` events:
```python
from services.extraction.jobs import accept_resource_available
accept_resource_available({
    "type": "resource.available",
    "tenant_id": str(verified_tenant_id),
    "version_id": str(persisted_resource_version_id),
})
```
**Never** feed public/unverified event dictionaries to this internal function.
The worker callable is `services.extraction.jobs.process_extraction` and
uses the existing Redis/RQ `somaloom` queue. Startup must make `services`
importable on worker PYTHONPATH. Output location:
`extractions/{version_id}/document.v1.json` under the tenant's object-store
namespace. Assets are stored in sibling `assets` prefix. For S3 configure
`SOMALOOM_STORAGE_BUCKET` and `SOMALOOM_KMS_KEY_ID` together.

When Redis dispatch fails, the DB job stays queued. Requeue it with:
```sh
python -c 'from services.extraction.jobs import reconcile; print(reconcile())'
```
Schedule reconciliation outside web request threads. Worker has a 900-second
job timeout, 40 MiB/400-page document and 250-asset caps; exceeding page/asset
caps yields `partial` and warnings. PDF processing catches page-local failures.
No untrusted paths or remote HTML image URLs are accepted.

## Known integration gates

1. Agent 1 to add a unique extraction claim and an atomic job-outbox migration;
   see `db/proposals/agent-3-extraction.sql`. Until then, simultaneous submissions
   can race; the in-service reconciliation is not transactional outbox delivery.
2. Agent 1 to mount the feature router in application composition and configure
   the resource/worker environment. Agent 2 to connect the available event.
3. Agent 4 to index only `needs_review=False` semantic blocks, and consult
   asset metadata before reproducing figures. Asset public export requires
   license checks; the API returns only metadata, not a public asset URL.
4. Agent 8 to convert verified LaTeX to editable OOXML OMML and final math
   typesetting. This module never asserts image-based equations are valid.
5. Production coverage remains necessary for layout reading order,
   multiscript OCR, complex math OCR, vector PDFs, and map obsolescence.
6. GitHub Actions are disabled for billing; run commands locally and report
   actual test outcomes. Do not interpret fixtures as evidence of OCR accuracy.

Metrics: `evaluation.py` calculates OCR word error rate, LaTeX exact-match
and visual-caption recall **only from supplied verified ground truth**. It
returns null if no eligible cases were provided. It never invents scores.

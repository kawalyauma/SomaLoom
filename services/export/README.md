# Agent 8 Publishing

Exporters consume the shared v1 `GeneratedDocument` and its structured
`body.sections[].blocks[]`. The libraries are never directly exposed as unauthenticated HTTP endpoints.
The authenticated FastAPI router looks up approved document versions by school,
checks staff roles and serves immutable exports from tenant-scoped object keys.

Install optional render requirements: `pip install -r services/export/requirements.txt`.
Call `export_pdf(document, branding, audience)` or `export_docx(...)`.

No visual is silently synthesized. Unknown/unlicensed asset references and
unsupported LaTeX must fail preflight; the source image service must resolve
tenant-scoped, licensed assets and inspect map labels before adding image
rendering. Student exports exclude answer and teacher blocks.

The export router is registered additively from app.main on this branch.
Its document-version and review routes use Agent 1's existing tables.
Agent 5 must persist an initial version; Agent 7 supplies separate marking
content. No claim of live EC2 deployment or completed visual-asset publishing.
\nApproval rejects fabricated or inaccessible evidence IDs and missing source\nlicense/URI metadata. The renderer stamps the persisted school's real name;\nlogo/approved asset resolution needs further Agent 1/3 integration.\n
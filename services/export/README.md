# Agent 8 Publishing

Exporters consume the shared v1 `GeneratedDocument` and its structured
`body.sections[].blocks[]`. They are libraries, **not** unauthenticated HTTP
endpoints. The owning FastAPI route must look up approved document versions by
authenticated school and apply role authorization before calling them.

Install optional render requirements: `pip install -r services/export/requirements.txt`.
Call `export_pdf(document, branding, audience)` or `export_docx(...)`.

No visual is silently synthesized. Unknown/unlicensed asset references and
unsupported LaTeX must fail preflight; the source image service must resolve
tenant-scoped, licensed assets and inspect map labels before adding image
rendering. Student exports exclude answer and teacher blocks.

Integration requested: Agent 1 registers an authenticated service router after
document-version persistence and approval contracts exist. Agent 5/7 supply
durable document/version/review routes. No claim of live export deployment.

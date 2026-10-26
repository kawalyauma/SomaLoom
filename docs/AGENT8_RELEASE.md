# Agent 8 — Web publishing integration and acceptance ledger

## Base and scope
This branch is based on Agent 1's draft foundation PR #9, not the sparse
published main, to preserve working session authentication and Next.js 16
bootstrap. Its PR targets `agent/01-platform` until that PR is merged.

## Live API contracts consumed
- Agent 1: `/api/v1/auth/login`, `/api/v1/auth/logout`,
  `/api/v1/users/me`, `/api/v1/schools`, `/api/v1/jobs/{id}`.
- Agent 2 (proposed in Issue #2): `/api/v1/resources`,
  `/api/v1/resources/uploads`, `/api/v1/imports/web`,
  `/api/v1/imports/telegram`.
- Agent 4 (proposed in Issue #4): `/api/v1/curricula`,
  `/api/v1/curricula/{id}/topics`, `/api/v1/search`.
- Agent 5 (proposed in Issue #5): `/api/v1/generations`,
  `/api/v1/generations/{id}`, `/api/v1/generations/{id}/draft`.
- Agent 7: `/api/v1/question-bank`.
- **Still require interface agreement**: persisted document listing/versions,
  per-block regeneration, approval/rejection API, publisher job submission
  and secure scoped download. UI proposes `GET /documents` and `POST /exports`,
  but must be reconciled with owners before declaring those pages live.

## Known limitations / release blockers
- UX is a functional first integration slice, not a full production acceptance.
- The visual editor edits paragraph and heading text locally. Versioned save,
  revision diff, resolved image assets and true math-browser rendering are
  outstanding and visibly labeled. Unsaved edits cannot be printed as approved.
- PDF equations render vector via Matplotlib SVG; Word equations become editable
  OMML for supported LaTeX constructs. Browser currently shows LaTeX source;
  KaTeX/MathJax integration remains to do. For visual assets, publish fails
  preflight rather than inventing imagery or using untrusted URLs.
- DOCX/PDF Python exporters are libraries pending approved version storage,
  tenant-authorized asset resolution and an authenticated API router.
- No native PostgreSQL, Docker, EC2 host, TLS, DNS, off-instance backup or
  restore was verified by this work. GitHub Actions intentionally not triggered.
- Cross-browser and real school educator acceptance remain outstanding.

## Local verification
```bash
cd apps/web
npm ci
npm run typecheck
npm run build

cd ../..
pip install -r services/export/requirements.txt
pip install pytest pypdf
pytest -q tests/test_agent8_publishing.py
```

## Manual end-to-end matrix (mark pass only with real API evidence)
1. Login / logout, revoked cookie, denied cross-tenant school — **pending deployed test**.
2. Upload owned educational resources; check provenance and job progress — **pending Agent 2**.
3. Explore licensed textbook diagrams, equations, curriculum and search evidence — **pending Agents 3–4**.
4. Run all six generators and view progress/draft/citations — **pending Agents 5–7**.
5. Edit paragraph, inspect quality, persist revision, approve document — **versioning API pending**.
6. Export A4 PDF and native-OMML DOCX, test student/teacher separation — **library unit tests only**.
7. Verify HTTPS on EC2, durability, backup and restore — **Agent 1 deployment pending**.

## Release procedure
Use Agent 1's Docker Compose and Nginx/HTTPS runbook. Merge in workstream
order after contract review. Keep AWS secrets in deployment configuration.
Validate live smoke tests and inspect representative PDF/DOCX files before
rolling traffic. Roll back to the preceding known-good image and database
migration policy from Agent 1; never silently reverse a destructive schema.

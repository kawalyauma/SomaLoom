# Release acceptance — 2026-10-26

No unrestricted public launch or production-readiness claim. Status is per essential acceptance environment; passing internal synthetic workflows does not satisfy real AI, official curriculum or educator acceptance. Main and the eight original agent branches remain unchanged. GitHub Actions stay manual-only and are not counted as passed checks.

## Module matrix

| Area | Status | Evidence / remaining gate |
|---|---|---|
| Authentication and school isolation | VERIFIED | Native login/logout/expiry, role and composite-FK/cross-school tests pass. Private browser journey tracked below. |
| PDF/DOCX uploads | VERIFIED | Native upload/dedup/permissions tests; actual private EC2 upload accepted PDF/DOCX/image with mandatory scanner after permission repair. |
| Telegram imports | BLOCKED | Webhook authentication/dedup and tenant tests pass; no dedicated test bot/chat/secret provided for a live import. |
| Authorized website CLI | VERIFIED | Real CLI acquired two original CC0 pages from the staging-owned site; temporary /32 ingress removed afterward. Both pages extracted/indexed on EC2; SSRF/robots tests also pass. |
| Document OCR and structural extraction | VERIFIED | Native PDF, DOCX tables/heading and real Tesseract scanned-PDF tests pass. Complex layouts/handwriting remain limited. |
| Visual and equation extraction | IMPLEMENTED — NOT VERIFIED | Structured math/crops and conservative diagram/map metadata tests pass; broad real textbook accuracy benchmark not provided. |
| Curriculum intelligence | IMPLEMENTED — NOT VERIFIED | Authoring/import/approval/outcome mapping pass with explicitly synthetic Uganda P5 enrichment. Official curriculum/educator validation pending. |
| Evidence retrieval and source references | VERIFIED | Native PostgreSQL lexical recall, exact-source checks, rights/tenant filters and stale-source tests pass. Semantic provider remains unconfigured. |
| AI provider execution | BLOCKED | Codex 0.164.0 flags/help inspected and safe failure/fallback tests pass. No dedicated credential or approved isolated application runner; no real inference claimed. |
| Lesson notes | IMPLEMENTED — NOT VERIFIED | Full synthetic-provider upload→RQ→research→validated teaching→review→PDF/DOCX passes. Real model/educator acceptance pending. |
| Exams and tests | IMPLEMENTED — NOT VERIFIED | Full synthetic-provider workflow passes, including exact marks, question validation and answer-free student files. Real model/educator acceptance pending. |
| Schemes of work | IMPLEMENTED — NOT VERIFIED | Full synthetic-provider workflow passes with calendar/week/period checks and editable schedule table. Real generation pending. |
| Lesson plans | IMPLEMENTED — NOT VERIFIED | Full synthetic-provider workflow passes with exact 40-minute stage allocations. Real generation pending. |
| Teacher guides | IMPLEMENTED — NOT VERIFIED | Full synthetic-provider workflow passes using distinct teaching template/validator. Real generation/educator review pending. |
| Marking guides | IMPLEMENTED — NOT VERIFIED | Separate teacher blocks/private endpoints and numerical/rubric tests pass. Real generated answer quality pending. |
| Question bank | VERIFIED | Native authenticated version/create/review/reuse/retire, duplicate, numerical/matching/diagram and school-denial tests pass; advanced authoring UI remains limited. |
| Editing, versioning and review | VERIFIED | Native immutable-version/optimistic save/role/attestation tests pass; old approvals do not approve new versions. Browser journey tracked below. |
| Professional PDF export | VERIFIED | Actual multipage PDF rendered and visually inspected: sharp fraction/root, reviewed science diagram, fictional campus-map legend, table, captions/source rights and page numbers. Student-answer removal passes. |
| Editable DOCX export | VERIFIED | Actual DOCX reopens with native OMML fractions/superscripts/roots, editable tables/text and two embedded original images. Student-answer removal passes; asynchronous RQ path passes. |
| EC2 deployment | IMPLEMENTED — NOT VERIFIED | New private encrypted EC2 staging built and all seven services healthy; real AI/Telegram, public DNS/TLS and complete production acceptance remain blocked. |
| Backup and restore | VERIFIED | Actual encrypted S3 download and disposable PostgreSQL restore: 39 tables, two QA users, five originals matched SHA-256, four published PDF/DOCX structures valid. Live data unchanged; production RPO/RTO not agreed. |
| Security checks | IMPLEMENTED — NOT VERIFIED | Native unauthorized/tenant/SSRF/CSRF/answer isolation tests pass. Python/npm audits clean; history secret scan clean after exact synthetic-key allowlist. External isolation/load/alert acceptance incomplete. |
| End-to-end workflow | IMPLEMENTED — NOT VERIFIED | Six full native synthetic-provider workflows pass. Real-provider source-grounded acceptance cannot pass without independent credentials/runtime. |
| Runtime monitoring and recoverability | IMPLEMENTED — NOT VERIFIED | Worker/dispatcher heartbeats and timeout recovery implemented; native queue/outbox/replay tests pass. Host metrics/timers installed and CloudWatch reports zero unhealthy services; alarms exist. Notification delivery remains blocked. |

## Executed verification

- Foundation baseline: 16 passed / 2 skipped (SQLite); 18 passed native PostgreSQL/Redis.
- Final isolated native runner: **110 passed, 0 failed, 0 skipped**, PostgreSQL 16/pgvector and Redis/RQ. Includes all six source-to-review/export families, real Tesseract OCR and reviewed visual export. Alembic metadata comparison clean. Fresh full upgrade/downgrade/upgrade and populated foundation-preservation downgrade passed.
- Asynchronous export addition: the same **110 passed** with DOCX executed through the real durable RQ export path. Migration a7ddca613219 follows consolidated 06a413e11f8b and immutable 0001_foundation.
- Python Ruff lint/format and compilation passed. TypeScript and Next.js 16 production build passed under Node 22. API image actually built; private EC2 API/web/worker/dispatcher/migrate images built and started, no public database/Redis ports.
- Python audit: no known vulnerabilities after Pillow 13 / pip 26.2.2 / pytest 9.1.1 updates. npm audit: zero vulnerabilities. Gitleaks historical scan passed; exact synthetic/diagram fixture string is allowlisted, not an actual secret.
- Representative original CC0 QA document: DOCX structure/native OMML/two images checked; five PDF pages reopened/rendered; first two pages visually inspected for math, table, diagram, visible map legend and clipping. QA references are original fixtures, not invented textbook citations.
- A shared-database run was invalidated by an overlapping migration drill (107 pass / 1 UndefinedTable failure); it is excluded. The isolated runner sequences tests and migration drills and passed.

## External/private staging gates

Instance i-0ec4689316dbd2d9d, private SSM-only access. All seven long-running services healthy and HTTPS /api/v1/ready returned ready. Browser testing found and repaired unreadable ClamAV definitions and stale Nginx upstream DNS after API recreation; final browser result is recorded below when complete. No failure has been relabeled as a pass.

BLOCKED: dedicated isolated Codex runtime/credential or independently authenticated API key; Telegram bot/chat/webhook credentials; owner-provided public hostname/DNS/TLS; official permitted curriculum fixtures and educator academic acceptance; notification destination for actual alert delivery. These gates are not replaced by mocks, screenshots or a healthy HTTP endpoint.

## Review/release disposition

Prepare a draft integration PR with all source work traceable to #9, #13, #12, #10, #15, #11, #14 and #16. Do not merge main or mark the platform production-ready while the real-provider and external acceptance gates remain unresolved. A limited private beta requires explicit owner acceptance of the documented noncritical gaps.

## Final private EC2 evidence (verified again 2026-10-27)

- Chromium journey PASSED against real HTTPS staging: login, real PDF/DOCX/image uploads with mandatory ClamAV, curriculum/topic selection, honest 503 for unconfigured AI, document edit/new version, review, authenticated PDF/DOCX downloads. Original browser draft was explicitly manually seeded QA data, never claimed as model output.
- Browser widths 1440/390/768 passed overflow checks. Axe smoke: zero serious/critical findings after correcting two text colors and the page landmark. Reopened downloaded student files omit the teacher QA answer.
- Real terminal importer acquired two owned-site CC0 HTML resources with source attribution. Acquisition was temporarily reachable only from the administration host /32; SG ingress returned to an empty list. All five total originals completed extraction. PostgreSQL contains 14 knowledge items. Real RQ topic research succeeded with five supporting permitted sources, explicitly nonofficial synthetic P5 enrichment.
- Off-instance restore backup `20261026T212247Z-a9af3e7e`: all archive checksums passed; 39 restored tables, two users, five original hashes, four exported PDF/DOCX structures verified in a disposable environment. Live database untouched.
- Seven staging services healthy after replacement/restart; API ready, worker and dispatcher active. Encrypted EBS verified through EC2 for both 30/60 GiB disks. Monitoring and daily backup timers active. Host metrics reported zero unhealthy services and 0.1% data disk usage. Notification actions remain disabled until the owner supplies a destination.
- No unresolved inline review threads were returned for any of PRs #9–#16. Relevant Issue #2/#4/#5/#7/#8 coordination comments were inspected and incorporated.

Sanitized commands/results: [verification evidence](verification/2026-10-26/). Native source-to-six-family tests deliberately use a synthetic provider. Real Codex/API and Telegram acceptance remain BLOCKED. Public hostname/TLS and educator acceptance remain BLOCKED. This is an integrated, privately staged review candidate, not a production-ready release.

The final Chromium run exercised review attestations and asynchronous PDF/DOCX publication through the actual browser forms, including RQ polling and authenticated downloads. It passed again on 2026-10-27. The default local suite passed 108 tests with two explicitly skipped native-service checks; the separate disposable native runner executes those checks.

## Review and release references

- [Master integration PR #17](https://github.com/kawalyauma/SomaLoom/pull/17) (draft; main unchanged).
- [Verified integration snapshot 8f3704d9](https://github.com/kawalyauma/SomaLoom/commit/8f3704d9edfddf3ca0e4c1c78e16d6f4b3a8fc8f). The published tree matches tested local integration snapshot 8756cf5834d64ae12974ea7ef6351e58b5a5984e; original PR heads are preserved as ancestry.
- Detailed local integration commits are retained on `integration/somaloom-release-local-20261027`; no work was discarded or force pushed.

# Verification ledger — 26 October 2026

## Executed evidence

| Check | Result | Scope / limitation |
|---|---|---|
| `pytest -q` | 16 passed, 2 skipped | SQLite/fake Redis; tests cover auth expiry/logout, role denial, tenant filtering, composite FK denial, all 11 schemas/fixtures/mock endpoints, storage traversal and immutability, queue execution and rate-limit behavior |
| Live Redis integration test | 1 passed, 1 skipped | Redis 7.0.15 with real RQ execution; PostgreSQL test skipped |
| Live API/web/worker smoke | Passed | Started separate Redis, FastAPI, RQ worker and production Next.js processes in the same environment; tested readiness, queued job execution and web-proxied login/profile/logout/revoked-session denial; database was SQLite |
| Ruff lint and format | Passed | Entire repository Python source |
| Next.js build and TypeScript | Passed | Next.js 16.4.3 production build and `tsc --noEmit` |
| npm production dependency audit | Passed, zero findings | `npm audit --omit=dev --audit-level=high` |
| Gitleaks scan | Passed, no leaks | Gitleaks 8.16.0 on exported tracked repository files; runtime .env excluded |
| Contract regeneration | Passed, no drift | JSON Schema, all 11 fixtures and OpenAPI regeneration |
| Compose validation | Passed | Compose v2.40.3 parsed both development and merged production configurations using `config --quiet`; no Docker daemon was available |
| Shell / YAML syntax | Passed | Deployment, migration, backup/restore scripts; workflows and Compose |
| Alembic offline SQL generation | Passed | PostgreSQL upgrade/downgrade SQL |
| PostgreSQL-WASM supplemental check | Passed | PGlite 0.5.12 + pgvector executed full schema up/down/up, HNSW creation and vector distance; verified app role cannot create tables or update audit logs. Offline replay keeps Alembic's version table, so replay uses `IF NOT EXISTS` for that table only. This is not native PostgreSQL/psycopg or Docker verification. |

Native PostgreSQL tests and real Compose builds/startup are defined in `.github/workflows/ci.yml`. They have **not** passed: GitHub Actions could not start any jobs. Run [40376980274](https://github.com/kawalyauma/SomaLoom/actions/runs/40376980274) annotations state: “The job was not started because your account is locked due to a billing issue.” All three jobs had empty step lists. Fix GitHub billing/account access, then rerun CI. Do not interpret runner failure as executed test results.

## Issue #1 acceptance gates

| Acceptance criterion | Current status |
|---|---|
| One-command setup and authenticated web/API integration | Setup prepared; web/API integration tested with SQLite; native Docker startup still unverified |
| EC2 HTTPS and lifecycle/migrations | Configuration and SQL verified as above; actual host/DNS/TLS unavailable |
| Tenant and role isolation | Tested at API and relational layers locally; repeat against native PostgreSQL in CI |
| Upload/generation job tracking contracts | Implemented common status lookup, schemas and fixtures; feature submission owned by Agents 2 and 5 |
| Encrypted durable storage and off-instance backup/restore | Immutable storage adapters and scripts implemented; actual EBS encryption, S3 upload and restore not verified |
| Passing CI, observability and recovery | CI blocked by GitHub billing; runbooks, health checks and log rotation prepared; cloud alert delivery and staging deployment need actual resources |
| No critical/high findings at launch | Auth/security tests, npm production audit and secrets scan passed within their scopes; full product/infrastructure review remains required |

## External prerequisites still missing

- EC2 host access, public DNS and valid TLS certificates.
- Dedicated encrypted EBS mount and verified S3/KMS/IAM resources.
- Off-instance restore drill with recorded counts/checksums, sample references and measured RPO/RTO.
- GitHub Actions account billing resolution and successful native CI execution.
- Deployed staging environment, restricted deployment identity and protected automated deployment configuration.
- Tested CloudWatch alerts/log forwarding and certificate renewal on the actual host.
- Agents 2–8 integration, feature outbox/retry behavior and complete end-to-end product checks.

Issue #1 remains open. The foundation is a reviewable implementation with explicit deployment gates; it is not declared production complete.

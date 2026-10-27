# Foundation decisions

- A Python monorepo package exposes `app`, central `contracts` and isolated `services` packages. Feature routers import contracts; Agent 1 registers routers. Agent 8 owns final UI.
- Tenant is a school; organizations group schools. MVP users belong to one school, platform admins to none. A later multi-school membership change requires a versioned contract and migration. Tenant selectors in user-submitted bodies never grant access.
- PostgreSQL rows have UUIDs, UTC timestamps and foreign keys. Composite (id, tenant_id) references prevent cross-school domain links. Runtime role has DML without DDL or audit mutation; database owner is migration-only. PostgreSQL RLS is not enabled: every feature must enforce query filtering as well as composite relationships.
- Server-side opaque 384-bit session tokens are SHA-256 hashed at rest and expire after 12 hours by default. Argon2id protects passwords. Browser tokens are HttpOnly cookies; protected native clients may send the same token as Bearer. Login currently issues cookies only. No public registration, refresh tokens or developer Codex sessions. CLI bootstrap prompts for credentials interactively.
- RQ/Redis provides workers and heartbeat. Job states live in background_jobs and job-specific tables. Real upload/generation submission and transactional outboxes belong to feature owners. No fake successful generation is returned.
- Knowledge embeddings use pgvector vector(1536) with HNSW cosine index, plus tenant_id filtering. Agent 4 must propose another dimensionality/index if its provider differs; fixed dimensions are explicit to avoid incompatible inserts.
- Resources use tenant-prefixed immutable version object keys. LocalObjectStore writes atomically; encrypted EBS is verified at host layer. S3ObjectStore supports later migration with instance-role credentials and SSE-KMS. File paths do not cross the API boundary. Large streaming/multipart interfaces and quotas are future feature work, not the current byte-oriented adapter's capability.
- Runtime AI exposes an async provider protocol, disabled until Agent 5 configures a supported provider. Codex CLI is a development tool unless Agent 5 builds a compliant runtime integration with independent credentials. No shell API exists.
- References, extracted visuals, equation LaTeX and evidence retain provenance. Versioned contracts distinguish persistent records from asynchronous status envelopes.

## API inventory

Working endpoints: GET health/ready/config/users/me/organizations/schools/schools/{id}/jobs/{id}; POST auth/login/auth/logout/users/organizations/schools. All except health/ready/OpenAPI/docs require authentication. Admin provisioning uses POST users; first platform admin uses the CLI. Mutations using cookies and login require an allowed Origin.

Development-only `/mocks/{contract}` (11 typed fixtures) is authenticated, returns a synthetic Resource fixture and is 404 outside development. Feature pipelines are reserved interfaces, not implemented endpoints. `contracts/v1/openapi.json` records exact request/response schemas. Errors exclude raw validation inputs; request IDs are generated server-side.

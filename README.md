# SomaLoom

Educational content intelligence for schools: resources → extraction → evidence → generation → review → export.

## Development

Requires Docker Engine with Compose v2. Run `python3 tools/init_dev_env.py && docker compose up --build -d --wait`. Web: http://localhost:3000, API docs: http://localhost:8000/api/v1/docs. Production requires separate TLS configuration; see `docs/DEPLOYMENT.md`.

Python: `python3 -m venv .venv && .venv/bin/pip install -r requirements.lock && .venv/bin/pip install --no-deps -e .`. Run `.venv/bin/pytest` and `.venv/bin/ruff check .`. Web: `cd apps/web && npm ci && npm run dev`.

## Agent workstreams

Read [integration rules](docs/AGENT_INTEGRATION.md) before branching. Agent 1 owns infrastructure, authentication, contracts and migrations. Feature services are reserved for agents 2–8; placeholders are not finished features. Runtime AI uses a provider interface, never developer login credentials.

## Architecture

Next.js App Router + TypeScript + Tailwind; FastAPI + Pydantic + SQLAlchemy/Alembic; PostgreSQL/pgvector; Redis/RQ; Nginx and persistent encrypted EC2 volumes. API prefix `/api/v1`. See `contracts/v1` for central schemas and fixtures.

## Launch gate

An accessible EC2 host, DNS, TLS certificates, encrypted EBS, S3 backup bucket and IAM role are required for production verification. Do not consider production deployed until HTTPS, restore, isolation and smoke checks pass. Launch/beta dates are targets, not evidence of readiness.

Provision the first administrator: `docker compose exec api python tools/provision_admin.py`. No public registration is enabled. See [architecture](docs/ARCHITECTURE.md), [deployment and recovery](docs/DEPLOYMENT.md) and [verification evidence](docs/VERIFICATION.md).

-- Agent 2 proposal only. Agent 1 must convert to a numbered Alembic revision.
-- Requires foundation 0001 and PostgreSQL 16. Do not execute at API startup.
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES schools(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    kind varchar(20) NOT NULL,
    status varchar(20) NOT NULL,
    checkpoint json NOT NULL,
    report json NOT NULL,
    error text,
    source_id uuid NOT NULL,
    job_id uuid NOT NULL,
    CONSTRAINT uq_ingestion_runs_id UNIQUE(id, tenant_id),
    CONSTRAINT fk_ingestion_runs_source FOREIGN KEY(source_id, tenant_id)
        REFERENCES import_sources(id, tenant_id),
    CONSTRAINT fk_ingestion_runs_job FOREIGN KEY(job_id, tenant_id)
        REFERENCES background_jobs(id, tenant_id)
);
CREATE INDEX IF NOT EXISTS ix_ingestion_runs_tenant_id ON ingestion_runs(tenant_id);
CREATE TABLE IF NOT EXISTS ingestion_outbox (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES schools(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    event_type varchar(80) NOT NULL,
    payload json NOT NULL,
    state varchar(20) NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    version_id uuid NOT NULL,
    job_id uuid NOT NULL,
    CONSTRAINT uq_ingestion_outbox_id UNIQUE(id, tenant_id),
    CONSTRAINT uq_ingestion_outbox_version_event UNIQUE(version_id, event_type),
    CONSTRAINT fk_ingestion_outbox_version FOREIGN KEY(version_id, tenant_id)
        REFERENCES resource_versions(id, tenant_id),
    CONSTRAINT fk_ingestion_outbox_job FOREIGN KEY(job_id, tenant_id)
        REFERENCES background_jobs(id, tenant_id)
);
CREATE INDEX IF NOT EXISTS ix_ingestion_outbox_tenant_id ON ingestion_outbox(tenant_id);
CREATE INDEX IF NOT EXISTS ix_ingestion_outbox_pending ON ingestion_outbox(state, updated_at);
CREATE TABLE IF NOT EXISTS telegram_receipts (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES schools(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    chat_id varchar(80) NOT NULL,
    message_id varchar(80) NOT NULL,
    file_unique_id varchar(200),
    payload json NOT NULL,
    state varchar(20) NOT NULL,
    source_id uuid NOT NULL,
    job_id uuid NOT NULL,
    CONSTRAINT uq_telegram_receipts_id UNIQUE(id, tenant_id),
    CONSTRAINT uq_telegram_receipts_chat_message UNIQUE(tenant_id, chat_id, message_id),
    CONSTRAINT fk_telegram_receipts_source FOREIGN KEY(source_id, tenant_id)
        REFERENCES import_sources(id, tenant_id),
    CONSTRAINT fk_telegram_receipts_job FOREIGN KEY(job_id, tenant_id)
        REFERENCES background_jobs(id, tenant_id)
);
CREATE INDEX IF NOT EXISTS ix_telegram_receipts_tenant_id ON telegram_receipts(tenant_id);
-- Per-tenant concurrent checksum imports are serialized by PostgreSQL
-- advisory transaction locks in the ingestion library; no permanent checksum
-- uniqueness constraint, because deleted resources may be re-imported.

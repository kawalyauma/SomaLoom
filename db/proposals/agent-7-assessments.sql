-- Agent 7 migration proposal. Agent 1 owns the Alembic migration head.
-- PostgreSQL 16+. Apply as an additive transactional migration after platform 0001.
CREATE TABLE assessment_question_versions (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    question_id uuid NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    status varchar(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'retired')),
    fingerprint varchar(64) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, question_id, version)
);
CREATE INDEX ix_assessment_question_search
    ON assessment_question_versions (tenant_id, status, fingerprint);
CREATE INDEX ix_assessment_question_root
    ON assessment_question_versions (tenant_id, question_id, version DESC);

CREATE TABLE assessment_papers (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    status varchar(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'published')),
    spec jsonb NOT NULL,
    sections jsonb NOT NULL,
    reviewer_id uuid,
    review_notes text,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (reviewer_id, tenant_id) REFERENCES users(id, tenant_id)
);
CREATE INDEX ix_assessment_papers_tenant_status
    ON assessment_papers (tenant_id, status);
-- Question revisions are immutable once created; the assessment JSON contains
-- pinned revision IDs and full snapshots so retired bank entries cannot change
-- an existing paper or marking guide. Service enforces school-scoped lookup.
-- Retention, publication audit, and snapshot encryption are platform policies.

-- REVIEW ONLY. DO NOT APPLY independently; Agent 1 coordinates migrations.
-- Serializable/idempotent resource-to-extraction claim and reliable queue dispatch.
CREATE UNIQUE INDEX IF NOT EXISTS uq_extractions_tenant_version_engine
  ON extractions(tenant_id, resource_version_id, engine);
CREATE TABLE IF NOT EXISTS extraction_outbox (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES schools(id),
  extraction_id UUID NOT NULL,
  job_id UUID NOT NULL,
  event_type VARCHAR(100) NOT NULL DEFAULT 'extraction.queued',
  dispatched_at TIMESTAMPTZ NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, extraction_id, event_type),
  FOREIGN KEY (extraction_id, tenant_id) REFERENCES extractions(id, tenant_id),
  FOREIGN KEY (job_id, tenant_id) REFERENCES background_jobs(id, tenant_id)
);
CREATE INDEX IF NOT EXISTS ix_extraction_outbox_pending
  ON extraction_outbox(created_at) WHERE dispatched_at IS NULL;
-- Rich provenance and confidence reside in immutable normalized object JSON for v1.
-- If Agent 4 needs SQL predicates, coordinate nullable metadata_json columns.

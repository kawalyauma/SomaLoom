-- Agent 4 ADDITIVE MIGRATION PROPOSAL for Agent 1 to convert into Alembic.
-- NOT applied automatically; Agent 1 owns db/migrations. Requires foundation schema,
-- PostgreSQL 16+ and pgvector extension with VECTOR(1536).
BEGIN;
CREATE TABLE curriculum_topics (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES schools(id),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 curriculum_id uuid NOT NULL, parent_id uuid,
 level varchar(80) NOT NULL, grade varchar(80) NOT NULL, subject varchar(120) NOT NULL,
 unit varchar(200) NOT NULL, title varchar(300) NOT NULL, kind varchar(30) NOT NULL,
 term integer, week integer, sequence integer NOT NULL DEFAULT 0,
 prerequisites json NOT NULL DEFAULT '[]'::json,
 source_uri text, source_license varchar(160),
 UNIQUE (id, tenant_id),
 FOREIGN KEY (curriculum_id, tenant_id) REFERENCES curricula(id, tenant_id),
 FOREIGN KEY (parent_id, tenant_id) REFERENCES curriculum_topics(id, tenant_id),
 CONSTRAINT ck_curriculum_topics_topic_kind CHECK (kind IN ('unit','topic','subtopic'))
);
CREATE INDEX ix_curriculum_topic_filter ON curriculum_topics (tenant_id, curriculum_id, grade, subject);

CREATE TABLE curriculum_outcome_mappings (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES schools(id),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 topic_id uuid NOT NULL, outcome_id uuid NOT NULL, required integer NOT NULL DEFAULT 1,
 origin varchar(24) NOT NULL, review_status varchar(24) NOT NULL DEFAULT 'draft',
 source_uri text, source_license varchar(160), reviewed_by uuid,
 revision integer NOT NULL DEFAULT 1, concepts json NOT NULL DEFAULT '[]'::json,
 UNIQUE (id, tenant_id), UNIQUE (tenant_id, topic_id, outcome_id),
 FOREIGN KEY (topic_id, tenant_id) REFERENCES curriculum_topics(id, tenant_id),
 FOREIGN KEY (outcome_id, tenant_id) REFERENCES learning_outcomes(id, tenant_id),
 FOREIGN KEY (reviewed_by, tenant_id) REFERENCES users(id, tenant_id),
 CONSTRAINT ck_curriculum_outcome_mappings_mapping_origin CHECK (origin IN ('official_candidate','enrichment')),
 CONSTRAINT ck_curriculum_outcome_mappings_mapping_review CHECK (review_status IN ('draft','approved','rejected')),
 CONSTRAINT ck_curriculum_outcome_mappings_mapping_required CHECK (required IN (0,1))
);

CREATE TABLE knowledge_index_items (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES schools(id),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 resource_id uuid NOT NULL, resource_version_id uuid NOT NULL,
 source_kind varchar(20) NOT NULL, source_id uuid NOT NULL, chunk_no integer NOT NULL,
 content_block_id uuid, visual_asset_id uuid, equation_id uuid,
 text text NOT NULL, page integer NOT NULL, fingerprint varchar(64) NOT NULL,
 source_uri text NOT NULL, license varchar(160) NOT NULL, access_approved boolean NOT NULL,
 embedding_model varchar(120), embedding vector(1536), metadata_json json NOT NULL DEFAULT '{}'::json,
 UNIQUE(id, tenant_id), UNIQUE(tenant_id, resource_version_id, source_kind, source_id, chunk_no),
 FOREIGN KEY (resource_id, tenant_id) REFERENCES resources(id, tenant_id),
 FOREIGN KEY (resource_version_id, tenant_id) REFERENCES resource_versions(id, tenant_id),
 FOREIGN KEY (content_block_id, tenant_id) REFERENCES content_blocks(id, tenant_id),
 FOREIGN KEY (visual_asset_id, tenant_id) REFERENCES visual_assets(id, tenant_id),
 FOREIGN KEY (equation_id, tenant_id) REFERENCES equations(id, tenant_id),
 CONSTRAINT ck_knowledge_index_items_item_one_source CHECK (
   (CASE WHEN content_block_id IS NOT NULL THEN 1 ELSE 0 END) +
   (CASE WHEN visual_asset_id IS NOT NULL THEN 1 ELSE 0 END) +
   (CASE WHEN equation_id IS NOT NULL THEN 1 ELSE 0 END) = 1),
 CONSTRAINT ck_knowledge_index_items_item_positive_page CHECK (page >= 1)
);
CREATE INDEX ix_knowledge_item_resource ON knowledge_index_items (tenant_id, resource_version_id);
CREATE INDEX ix_knowledge_item_fingerprint ON knowledge_index_items (tenant_id, fingerprint);
CREATE INDEX ix_knowledge_keyword ON knowledge_index_items
 USING GIN (to_tsvector('simple', text));
CREATE INDEX ix_knowledge_embedding ON knowledge_index_items
 USING hnsw (embedding vector_cosine_ops);

CREATE TABLE topic_research_records (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES schools(id),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 topic_id uuid NOT NULL, requested_by uuid NOT NULL,
 bundle json NOT NULL, review_status varchar(20) NOT NULL,
 index_version varchar(64) NOT NULL, curriculum_revision integer NOT NULL,
 content_version integer NOT NULL,
 UNIQUE(id, tenant_id),
 FOREIGN KEY (topic_id, tenant_id) REFERENCES curriculum_topics(id, tenant_id),
 FOREIGN KEY (requested_by, tenant_id) REFERENCES users(id, tenant_id)
);
CREATE INDEX ix_research_topic ON topic_research_records (tenant_id, topic_id);

CREATE TABLE topic_research_sources (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES schools(id),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 record_id uuid NOT NULL, index_item_id uuid NOT NULL, resource_version_id uuid NOT NULL,
 UNIQUE (id, tenant_id), UNIQUE (tenant_id, record_id, index_item_id),
 FOREIGN KEY (record_id, tenant_id) REFERENCES topic_research_records(id, tenant_id),
 FOREIGN KEY (index_item_id, tenant_id) REFERENCES knowledge_index_items(id, tenant_id) ON DELETE CASCADE,
 FOREIGN KEY (resource_version_id, tenant_id) REFERENCES resource_versions(id, tenant_id)
);

CREATE TABLE knowledge_outbox (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES schools(id),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 job_id uuid NOT NULL, status varchar(20) NOT NULL, attempts integer NOT NULL DEFAULT 0,
 payload json NOT NULL, last_error text,
 UNIQUE (id, tenant_id), UNIQUE(job_id, tenant_id),
 FOREIGN KEY (job_id, tenant_id) REFERENCES background_jobs(id, tenant_id)
);
CREATE INDEX ix_outbox_status ON knowledge_outbox(status, created_at);
COMMIT;

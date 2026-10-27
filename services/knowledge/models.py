"""Knowledge and research feature tables; migration belongs to Agent 1."""

from app.core.models import col, domain
from app.core.vector import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)

items = domain(
    "knowledge_index_items",
    [
        col("resource_id", Uuid),
        col("source_kind", String(20)),
        col("source_id", Uuid),
        col("chunk_no", Integer),
        col("text"),
        col("page", Integer),
        col("fingerprint", String(64)),
        col("source_uri"),
        col("license", String(160)),
        col("access_approved", Boolean),
        col("embedding_model", String(120), True),
        Column("embedding", Vector(1536).with_variant(JSON(), "sqlite"), nullable=True),
        col("metadata_json", JSON),
    ],
    [
        ("resource_version_id", "resource_versions"),
        ("content_block_id", "content_blocks", True),
        ("visual_asset_id", "visual_assets", True),
        ("equation_id", "equations", True),
    ],
)
items.append_constraint(
    UniqueConstraint("tenant_id", "resource_version_id", "source_kind", "source_id", "chunk_no")
)
items.append_constraint(
    CheckConstraint(
        "(CASE WHEN content_block_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN visual_asset_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN equation_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
        name="item_one_source",
    )
)
items.append_constraint(CheckConstraint("page >= 1", name="item_positive_page"))
items.append_constraint(
    ForeignKeyConstraint(["resource_id", "tenant_id"], ["resources.id", "resources.tenant_id"])
)
Index("ix_knowledge_item_resource", items.c.tenant_id, items.c.resource_version_id)
Index("ix_knowledge_item_fingerprint", items.c.tenant_id, items.c.fingerprint)
Index(
    "ix_knowledge_items_embedding",
    items.c.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
).ddl_if(dialect="postgresql")
Index(
    "ix_knowledge_items_keyword",
    text("to_tsvector('simple', text)"),
    _table=items,
    postgresql_using="gin",
).ddl_if(dialect="postgresql")

research_records = domain(
    "topic_research_records",
    [
        col("bundle", JSON),
        col("review_status", String(20)),
        col("index_version", String(64)),
        col("curriculum_revision", Integer),
        col("content_version", Integer),
        col("requested_by", Uuid),
    ],
    [("topic_id", "curriculum_topics")],
)
research_records.append_constraint(
    ForeignKeyConstraint(["requested_by", "tenant_id"], ["users.id", "users.tenant_id"])
)
Index("ix_research_topic", research_records.c.tenant_id, research_records.c.topic_id)

research_sources = domain(
    "topic_research_sources",
    [],
    [
        ("record_id", "topic_research_records"),
        ("index_item_id", "knowledge_index_items"),
        ("resource_version_id", "resource_versions"),
    ],
)
research_sources.append_constraint(UniqueConstraint("tenant_id", "record_id", "index_item_id"))

outbox = domain(
    "knowledge_outbox",
    [
        col("status", String(20)),
        col("attempts", Integer),
        col("payload", JSON),
        col("last_error", Text, True),
    ],
    [("job_id", "background_jobs")],
)
outbox.append_constraint(UniqueConstraint("job_id", "tenant_id"))

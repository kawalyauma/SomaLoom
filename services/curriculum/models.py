"""Feature tables; Agent 1 integrates db/proposals/agent-04-knowledge.sql."""
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid
from app.core.models import col, domain

topics = domain("curriculum_topics", [
    col("level", String(80)), col("grade", String(80)),
    col("subject", String(120)), col("unit", String(200)),
    col("title", String(300)), col("kind", String(30)),
    col("term", Integer, True), col("week", Integer, True),
    col("sequence", Integer), col("prerequisites", JSON),
    col("source_uri", Text, True), col("source_license", String(160), True),
], [("curriculum_id", "curricula"), ("parent_id", "curriculum_topics", True)])
topics.append_constraint(CheckConstraint("kind IN ('unit','topic','subtopic')", name="topic_kind"))
Index("ix_curriculum_topic_filter", topics.c.tenant_id, topics.c.curriculum_id, topics.c.grade, topics.c.subject)

mappings = domain("curriculum_outcome_mappings", [
    col("required", Integer), col("origin", String(24)),
    col("review_status", String(24)), col("source_uri", Text, True),
    col("source_license", String(160), True), col("reviewed_by", Uuid, True),
    col("revision", Integer), col("concepts", JSON),
], [("topic_id", "curriculum_topics"), ("outcome_id", "learning_outcomes")])
mappings.append_constraint(UniqueConstraint("tenant_id", "topic_id", "outcome_id"))
mappings.append_constraint(CheckConstraint("origin IN ('official_candidate','enrichment')", name="mapping_origin"))
mappings.append_constraint(CheckConstraint("review_status IN ('draft','approved','rejected')", name="mapping_review"))
mappings.append_constraint(CheckConstraint("required IN (0,1)", name="mapping_required"))
mappings.append_constraint(
    # Reviewer must belong to the same school; database foreign key prevents forged reviewer IDs.
    ForeignKeyConstraint(
        ["reviewed_by", "tenant_id"], ["users.id", "users.tenant_id"]
    )
)

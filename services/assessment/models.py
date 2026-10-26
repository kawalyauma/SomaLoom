"""SQLAlchemy domain tables. Import alongside Agent 1 Base before running migrations."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (JSON, CheckConstraint, Column, DateTime, ForeignKey,
                        ForeignKeyConstraint, Index, Integer, String, Table,
                        Text, UniqueConstraint, Uuid)

from app.core.models import Base


def utcnow():
    return datetime.now(timezone.utc)


question_versions = Table(
    "assessment_question_versions", Base.metadata,
    Column("id", Uuid, primary_key=True, default=uuid4),
    Column("tenant_id", Uuid, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
    Column("question_id", Uuid, nullable=False),
    Column("version", Integer, nullable=False),
    Column("status", String(20), nullable=False, default="draft"),
    Column("fingerprint", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow),
    UniqueConstraint("tenant_id", "question_id", "version"),
    UniqueConstraint("tenant_id", "id"),
    CheckConstraint("version >= 1", name="question_version_positive"),
    CheckConstraint("status IN ('draft','approved','retired')", name="question_status"),
)
Index("ix_assessment_question_search", question_versions.c.tenant_id,
      question_versions.c.status, question_versions.c.fingerprint)

papers = Table(
    "assessment_papers", Base.metadata,
    Column("id", Uuid, primary_key=True, default=uuid4),
    Column("tenant_id", Uuid, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
    Column("status", String(20), nullable=False, default="draft"),
    Column("spec", JSON, nullable=False),
    Column("sections", JSON, nullable=False),
    Column("reviewer_id", Uuid, nullable=True),
    Column("review_notes", Text, nullable=True),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow),
    UniqueConstraint("tenant_id", "id"),
    ForeignKeyConstraint(["reviewer_id", "tenant_id"], ["users.id", "users.tenant_id"]),
    CheckConstraint("status IN ('draft','published')", name="assessment_status"),
)
Index("ix_assessment_papers_tenant_status", papers.c.tenant_id, papers.c.status)

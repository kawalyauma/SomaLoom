"""Platform-owned schema. Additive feature changes require a migration proposal."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.vector import Vector


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def utcnow():
    return datetime.now(timezone.utc)


class Identity:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Organization(Identity, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(200))


class School(Identity, Base):
    __tablename__ = "schools"
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))


class User(Identity, Base):
    __tablename__ = "users"
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("schools.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        CheckConstraint(
            "role IN ('platform_admin','school_admin','teacher','reviewer')", name="role"
        ),
        CheckConstraint(
            "(role = 'platform_admin' AND tenant_id IS NULL) OR (role <> 'platform_admin' AND tenant_id IS NOT NULL)",
            name="tenant_role",
        ),
    )


class AuthSession(Identity, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Identity, Base):
    __tablename__ = "audit_logs"
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("schools.id"), index=True)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[str | None] = mapped_column(String(100))
    request_id: Mapped[str | None] = mapped_column(String(36))


class BackgroundJob(Identity, Base):
    __tablename__ = "background_jobs"
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("schools.id"), index=True)
    kind: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress"),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')", name="status"
        ),
    )


def relation(name, target, nullable=False):
    return (
        Column(name, Uuid, nullable=nullable),
        ForeignKeyConstraint([name, "tenant_id"], [f"{target}.id", f"{target}.tenant_id"]),
    )


def domain(name, fields, links=()):
    cols = [
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("tenant_id", Uuid, ForeignKey("schools.id"), nullable=False, index=True),
        Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
        Column(
            "updated_at", DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
        ),
        UniqueConstraint("id", "tenant_id"),
    ]
    cols.extend(fields)
    for field, target, *optional in links:
        cols.extend(relation(field, target, optional[0] if optional else False))
    return Table(name, Base.metadata, *cols)


def col(name, type_=Text, nullable=False):
    return Column(name, type_, nullable=nullable)


sources = domain(
    "import_sources",
    [col("kind", String(30)), col("source_uri"), col("license"), col("config", JSON)],
)
resources = domain(
    "resources",
    [col("title", String(500)), col("media_type", String(200)), col("provenance", JSON)],
    [("import_source_id", "import_sources", True)],
)
resource_versions = domain(
    "resource_versions",
    [
        col("version", Integer),
        col("object_key"),
        col("checksum_sha256", String(64)),
        col("provenance", JSON),
    ],
    [("resource_id", "resources")],
)
resource_versions.append_constraint(UniqueConstraint("resource_id", "version"))
extractions = domain(
    "extractions",
    [col("engine", String(100))],
    [("resource_version_id", "resource_versions"), ("job_id", "background_jobs")],
)
blocks = domain(
    "content_blocks",
    [col("page", Integer), col("kind", String(50)), col("text"), col("bbox", JSON, True)],
    [("extraction_id", "extractions")],
)
visuals = domain(
    "visual_assets",
    [
        col("object_key"),
        col("kind", String(50)),
        col("page", Integer),
        col("caption", Text, True),
        col("provenance", JSON),
    ],
    [("extraction_id", "extractions")],
)
equations = domain(
    "equations",
    [col("page", Integer), col("latex"), col("confidence", Float)],
    [("extraction_id", "extractions")],
)
curricula = domain(
    "curricula",
    [col("name", String(200)), col("country", String(100)), col("version", String(100))],
)
outcomes = domain(
    "learning_outcomes",
    [col("code", String(100)), col("description")],
    [("curriculum_id", "curricula")],
)
knowledge = domain(
    "knowledge_records",
    [col("text"), col("metadata_json", JSON)],
    [("content_block_id", "content_blocks")],
)
evidence = domain(
    "evidence_links",
    [col("quote"), col("provenance", JSON)],
    [("content_block_id", "content_blocks"), ("outcome_id", "learning_outcomes", True)],
)
generations = domain(
    "generation_jobs",
    [col("document_type", String(50)), col("parameters", JSON)],
    [("job_id", "background_jobs"), ("requested_by", "users")],
)
generation_evidence = domain(
    "generation_evidence",
    [],
    [("generation_job_id", "generation_jobs"), ("evidence_id", "evidence_links")],
)
documents = domain(
    "generated_documents",
    [col("title", String(500)), col("document_type", String(50))],
    [("generation_job_id", "generation_jobs")],
)
versions = domain(
    "document_versions",
    [col("version", Integer), col("body", JSON)],
    [("document_id", "generated_documents")],
)
versions.append_constraint(UniqueConstraint("document_id", "version"))
reviews = domain(
    "document_reviews",
    [col("decision", String(30)), col("comments")],
    [("document_version_id", "document_versions"), ("reviewer_id", "users")],
)
exports = domain(
    "exports",
    [col("format", String(20)), col("object_key", Text, True)],
    [("document_version_id", "document_versions"), ("job_id", "background_jobs")],
)
publications = domain("publications", [col("visibility", String(20))], [("export_id", "exports")])


knowledge.append_column(
    Column("embedding", Vector(1536).with_variant(JSON(), "sqlite"), nullable=True)
)
Index(
    "ix_knowledge_embedding",
    knowledge.c.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
).ddl_if(dialect="postgresql")

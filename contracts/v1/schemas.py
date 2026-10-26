"""Central wire contracts; coordinate changes with Agent 1."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

class Role(StrEnum):
    platform_admin = "platform_admin"
    school_admin = "school_admin"
    teacher = "teacher"
    reviewer = "reviewer"

class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"

class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = "1.0"

class Provenance(BaseModel):
    source_uri: str
    license: str
    checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    imported_by: UUID | None = None

class Resource(Entity):
    title: str = Field(min_length=1, max_length=500)
    media_type: str
    provenance: Provenance

class ResourceVersion(Entity):
    resource_id: UUID
    version: int = Field(ge=1)
    object_key: str
    provenance: Provenance

class Job(Entity):
    status: JobStatus = JobStatus.queued
    progress: int = Field(default=0, ge=0, le=100)
    error: str | None = None
    finished_at: datetime | None = None

class Extraction(Job):
    resource_version_id: UUID

class ContentBlock(Entity):
    extraction_id: UUID
    page: int = Field(ge=1)
    kind: str
    text: str
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)

class VisualAsset(Entity):
    extraction_id: UUID
    object_key: str
    kind: str
    page: int = Field(ge=1)
    caption: str | None = None
    provenance: Provenance

class Equation(Entity):
    extraction_id: UUID
    page: int = Field(ge=1)
    latex: str
    confidence: float = Field(ge=0, le=1)

class CurriculumOutcome(Entity):
    curriculum_id: UUID
    code: str
    description: str

class EvidenceLink(Entity):
    content_block_id: UUID
    outcome_id: UUID | None = None
    quote: str
    provenance: Provenance

class GenerationJob(Job):
    document_type: str
    requested_by: UUID
    evidence_ids: list[UUID]
    parameters: dict[str, Any] = Field(default_factory=dict)

class GeneratedDocument(Entity):
    generation_job_id: UUID
    title: str
    document_type: str
    evidence_ids: list[UUID]
    body: dict[str, Any]

class Export(Job):
    document_version_id: UUID
    format: str = Field(pattern="^(pdf|docx)$")
    object_key: str | None = None

T = TypeVar("T")
class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any = None

class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str

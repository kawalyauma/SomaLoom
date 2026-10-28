"""Agent 5 draft contract. The foundation's GeneratedDocument.body stores this JSON."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentKind(StrEnum):
    lesson_notes = "lesson_notes"
    scheme_of_work = "scheme_of_work"
    lesson_plan = "lesson_plan"
    teacher_guide = "teacher_guide"
    exam = "exam"
    test = "test"
    quiz = "quiz"
    marking_guide = "marking_guide"
    assignment = "assignment"
    worksheet = "worksheet"


class GenerationInput(StrictModel):
    document_type: DocumentKind
    curriculum_id: UUID
    subject_id: UUID
    level_id: UUID
    topic_ids: list[UUID] = Field(min_length=1, max_length=30)
    options: dict[str, Any] = Field(default_factory=dict)
    resource_filters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded(self):
        import json

        if len(json.dumps(self.options)) + len(json.dumps(self.resource_filters)) > 12000:
            raise ValueError("Generation options exceed size limit")
        return self


class Outcome(StrictModel):
    id: UUID
    code: str
    description: str


class Passage(StrictModel):
    id: UUID
    outcome_id: UUID
    quote: str = Field(min_length=1, max_length=2500)
    source_title: str | None = None
    source_uri: str | None = None
    license: str | None = None


class VisualReference(StrictModel):
    id: UUID
    outcome_id: UUID
    kind: str
    caption: str | None = None
    page: int | None = Field(default=None, ge=1)
    source_uri: str | None = None
    license: str | None = None


class EvidenceBundle(StrictModel):
    outcomes: list[Outcome] = Field(min_length=1)
    passages: list[Passage] = Field(default_factory=list)
    visuals: list[VisualReference] = Field(default_factory=list)


class DraftBlock(StrictModel):
    type: str = Field(pattern="^(paragraph|heading|equation|table|visual|activity|question)$")
    text: str = ""
    latex: str | None = None
    table: list[list[str]] | None = None
    asset_ref: str | None = None
    citations: list[UUID] = Field(default_factory=list)
    verification: str = Field(
        default="unverified", pattern="^(source_supported|unverified|teacher_supplied|enrichment)$"
    )


class DraftSection(StrictModel):
    outcome_id: UUID
    heading: str
    blocks: list[DraftBlock] = Field(min_length=1)
    contradictions: list[str] = Field(default_factory=list)


class QualityReport(StrictModel):
    required_outcomes: int
    covered_outcomes: int
    coverage_percent: float
    verified_blocks: int
    unverified_blocks: int
    missing_outcome_ids: list[UUID] = Field(default_factory=list)
    unknown_citation_ids: list[UUID] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    human_review_required: bool = True


class StructuredDraft(StrictModel):
    schema_version: str = "1.0"
    metadata: dict[str, Any]
    document_type: DocumentKind
    curriculum_id: UUID
    learning_outcomes: list[Outcome]
    sections: list[DraftSection]
    references: list[Passage]
    visual_references: list[VisualReference] = Field(default_factory=list)
    quality_report: QualityReport
    review_state: str = "awaiting_review"


class GenerationStatus(StrictModel):
    id: UUID
    job_id: UUID
    status: str
    progress: int
    stage: str
    error: str | None = None
    document_id: UUID | None = None

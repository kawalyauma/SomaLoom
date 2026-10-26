"""Teaching studio v1: strict editable document and generation specifications.

These feature models supplement, rather than alter, contracts.v1.GeneratedDocument.
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeachingType(StrEnum):
    lesson_notes = "lesson_notes"
    scheme_of_work = "scheme_of_work"
    lesson_plan = "lesson_plan"
    teacher_guide = "teacher_guide"


class Depth(StrEnum):
    concise = "concise"
    standard = "standard"
    comprehensive = "comprehensive"


class Audience(StrEnum):
    teacher = "teacher"
    learner = "learner"


class BlockKind(StrEnum):
    paragraph = "paragraph"
    heading = "heading"
    list = "list"
    table = "table"
    equation = "equation"
    visual = "visual"
    visual_needed = "visual_needed"
    activity = "activity"
    question = "question"
    reflection = "reflection"


class Branding(StrictModel):
    school_name: str = Field(min_length=1, max_length=200)
    logo_asset_id: UUID | None = None
    motto: str | None = Field(default=None, max_length=300)


class TermCalendar(StrictModel):
    starts_on: date
    ends_on: date
    teaching_weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    excluded_dates: list[date] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_calendar(self) -> TermCalendar:
        if self.ends_on < self.starts_on:
            raise ValueError("calendar ends_on must be after starts_on")
        if not self.teaching_weekdays or any(day not in range(7) for day in self.teaching_weekdays):
            raise ValueError("teaching_weekdays must be weekday numbers 0 through 6")
        if len(set(self.teaching_weekdays)) != len(self.teaching_weekdays):
            raise ValueError("teaching_weekdays must be unique")
        if any(not self.starts_on <= day <= self.ends_on for day in self.excluded_dates):
            raise ValueError("excluded dates must fall within calendar")
        return self


class TeachingSpec(StrictModel):
    type: TeachingType
    curriculum_id: UUID
    curriculum_version: str = Field(min_length=1)
    level_id: UUID
    subject_id: UUID
    topic_ids: list[UUID] = Field(min_length=1)
    outcome_ids: list[UUID] = Field(min_length=1)
    country: str = Field(default="UG", min_length=2, max_length=2)
    audience: Audience = Audience.teacher
    depth: Depth = Depth.standard
    language: str = Field(default="en", min_length=2, max_length=20)
    academic_year: str | None = None
    term: str | None = None
    weeks: int | None = Field(default=None, ge=1, le=53)
    periods_per_week: int | None = Field(default=None, ge=1, le=50)
    period_minutes: int | None = Field(default=None, ge=1, le=240)
    calendar: TermCalendar | None = None
    lesson_date: date | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=480)
    teacher_name: str | None = None
    branding: Branding | None = None

    @model_validator(mode="after")
    def validate_type_fields(self) -> TeachingSpec:
        if len(set(self.topic_ids)) != len(self.topic_ids):
            raise ValueError("duplicate topic_ids")
        if len(set(self.outcome_ids)) != len(self.outcome_ids):
            raise ValueError("duplicate outcome_ids")
        if self.type == TeachingType.scheme_of_work:
            if not (self.calendar and self.term and self.academic_year
                    and self.weeks and self.periods_per_week and self.period_minutes):
                raise ValueError("schemes require calendar, term, year, weeks and periods")
        if self.type == TeachingType.lesson_plan:
            if not (self.lesson_date and self.duration_minutes):
                raise ValueError("lesson plans require lesson_date and duration_minutes")
        return self


class CurriculumTarget(StrictModel):
    id: UUID
    curriculum_id: UUID
    level_id: UUID
    subject_id: UUID
    topic_id: UUID
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    mandatory: bool = True


class EvidenceItem(StrictModel):
    id: UUID
    source_title: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    license: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    outcome_ids: list[UUID]
    page: int | None = Field(default=None, ge=1)
    asset_id: UUID | None = None
    asset_kind: str | None = None
    asset_permission_verified: bool = False


class EvidenceBundle(StrictModel):
    curriculum_id: UUID
    curriculum_version: str
    outcomes: list[CurriculumTarget] = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(min_length=1)
    required_visual_kinds: list[str] = Field(default_factory=list)


class TeachingBlock(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    kind: BlockKind
    text: str = ""
    latex: str | None = None
    mathml: str | None = None
    rows: list[list[str]] | None = None
    asset_id: UUID | None = None
    visual_instruction: str | None = None
    caption: str | None = None
    citation_ids: list[UUID] = Field(default_factory=list)
    outcome_ids: list[UUID] = Field(default_factory=list)
    requires_review: bool = False

    @model_validator(mode="after")
    def validate_media(self) -> TeachingBlock:
        if self.kind == BlockKind.equation and not (self.latex or self.mathml):
            raise ValueError("equation block must contain latex or mathml")
        if self.kind == BlockKind.table and not (self.rows and len(self.rows) >= 2):
            raise ValueError("table must have at least two rows")
        if self.kind == BlockKind.visual and not self.asset_id:
            raise ValueError("visual blocks require an existing licensed asset_id")
        if self.kind == BlockKind.visual_needed and not self.visual_instruction:
            raise ValueError("visual_needed blocks require a precise drawing instruction")
        if self.kind not in (BlockKind.equation, BlockKind.table, BlockKind.visual) and not (
            self.text.strip() or self.visual_instruction
        ):
            raise ValueError("content block cannot be empty")
        return self


class TeachingSection(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    blocks: list[TeachingBlock] = Field(default_factory=list)
    outcome_ids: list[UUID] = Field(default_factory=list)


class SchemeWeek(StrictModel):
    week: int = Field(ge=1)
    topic_id: UUID
    subtopics: list[str] = Field(min_length=1)
    outcome_ids: list[UUID] = Field(min_length=1)
    periods: int = Field(ge=1)
    methods: list[str] = Field(min_length=1)
    activities: list[str] = Field(min_length=1)
    resources: list[str] = Field(min_length=1)
    assessment: str = Field(min_length=1)
    citation_ids: list[UUID] = Field(min_length=1)
    remarks: str = ""


class LessonStage(StrictModel):
    key: Literal["introduction", "development", "assessment", "conclusion"]
    minutes: int = Field(ge=1)
    teacher_actions: list[str] = Field(min_length=1)
    learner_actions: list[str] = Field(min_length=1)
    assessment: str = Field(min_length=1)
    differentiation: str = Field(min_length=1)


class TeachingBody(StrictModel):
    schema_version: Literal["teaching.v1"] = "teaching.v1"
    sections: list[TeachingSection] = Field(min_length=1)
    scheme_weeks: list[SchemeWeek] = Field(default_factory=list)
    lesson_stages: list[LessonStage] = Field(default_factory=list)
    title: str = Field(min_length=1)
    review_status: Literal["needs_review", "approved"] = "needs_review"
    author_id: UUID | None = None
    reviewer_id: UUID | None = None
    revision: int = Field(default=1, ge=1)


class ValidationFinding(StrictModel):
    code: str
    severity: Literal["error", "warning"]
    message: str
    block_id: UUID | None = None


class TeachingValidation(StrictModel):
    valid: bool
    teacher_review_required: bool = True
    missing_outcome_ids: list[UUID] = Field(default_factory=list)
    findings: list[ValidationFinding] = Field(default_factory=list)


class TeachingResult(StrictModel):
    document: dict
    validation: TeachingValidation

"""Assessment-specific v1 models. Never expose internal answer payloads in learner DTOs."""
from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionType(StrEnum):
    multiple_choice = "multiple_choice"
    true_false = "true_false"
    short_answer = "short_answer"
    structured = "structured"
    essay = "essay"
    numerical = "numerical"
    matching = "matching"
    completion = "completion"
    data_interpretation = "data_interpretation"
    diagram_labeling = "diagram_labeling"
    practical = "practical"


class Difficulty(StrEnum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class SourceReference(StrictModel):
    evidence_id: UUID | None = None
    source_uri: str = Field(min_length=1, max_length=2048)
    license: str = Field(min_length=1, max_length=120)
    page: int | None = Field(default=None, ge=1)


class Option(StrictModel):
    id: str = Field(pattern=r"^[A-H]$")
    text: str = Field(min_length=1, max_length=3000)


class MarkPoint(StrictModel):
    criterion: str = Field(min_length=1, max_length=1000)
    marks: int = Field(ge=1, le=100)


class Answer(StrictModel):
    correct_option_ids: list[str] = Field(default_factory=list)
    acceptable_answers: list[str] = Field(default_factory=list)
    numeric_value: float | None = None
    tolerance: float = Field(default=0, ge=0)
    calculation: str | None = Field(default=None, max_length=1000)
    steps: list[MarkPoint] = Field(default_factory=list)
    rubric: list[MarkPoint] = Field(default_factory=list)
    explanation: str | None = None


class QuestionDraft(StrictModel):
    type: QuestionType
    curriculum_id: UUID
    level_id: UUID
    subject_id: UUID
    topic_ids: list[UUID] = Field(min_length=1, max_length=20)
    outcome_ids: list[UUID] = Field(default_factory=list)
    difficulty: Difficulty
    cognitive_target: str = Field(min_length=2, max_length=120)
    stem: str = Field(min_length=6, max_length=12000)
    marks: int = Field(ge=1, le=100)
    estimated_minutes: float = Field(gt=0, le=120)
    options: list[Option] = Field(default_factory=list)
    multiple_select: bool = False
    answer: Answer
    visual_asset_ids: list[UUID] = Field(default_factory=list)
    visual_verified: bool = False
    latex: str | None = Field(default=None, max_length=3000)
    source_refs: list[SourceReference] = Field(default_factory=list)
    provenance: Literal["original", "ai_generated", "licensed_import"]
    matching_pairs: dict[str, str] = Field(default_factory=dict)
    data_table: list[dict[str, str | float | int]] = Field(default_factory=list)

    @model_validator(mode="after")
    def verify_structure(self):
        if len(set(self.topic_ids)) != len(self.topic_ids):
            raise ValueError("Topic identifiers must be unique")
        if len(set(self.outcome_ids)) != len(self.outcome_ids):
            raise ValueError("Learning outcomes must be unique")
        if self.provenance == "licensed_import" and not self.source_refs:
            raise ValueError("Imported questions require a licensed source")
        ids = [o.id for o in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("Option identifiers must be distinct")
        if self.type in (QuestionType.multiple_choice, QuestionType.true_false):
            if self.type == QuestionType.multiple_choice and not (2 <= len(ids) <= 8):
                raise ValueError("Multiple choice requires 2 to 8 options")
            if self.type == QuestionType.true_false and sorted(o.text.lower().strip() for o in self.options) != ["false", "true"]:
                raise ValueError("True/false requires exactly True and False")
            if len({o.text.casefold().strip() for o in self.options}) != len(ids):
                raise ValueError("Answer options must be distinct")
            correct = self.answer.correct_option_ids
            if not correct or len(set(correct)) != len(correct) or not set(correct) <= set(ids):
                raise ValueError("Correct option identifiers must exist and be distinct")
            if not self.multiple_select and len(correct) != 1:
                raise ValueError("Single-select questions must have exactly one correct option")
        elif self.options or self.answer.correct_option_ids or self.multiple_select:
            raise ValueError("Answer options are allowed only on choice questions")
        if self.type == QuestionType.numerical and self.answer.numeric_value is None:
            raise ValueError("Numerical problems require a numeric answer")
        if self.type == QuestionType.matching and len(self.matching_pairs) < 2:
            raise ValueError("Matching requires at least two pairs")
        if self.type in (QuestionType.diagram_labeling,) and (
            not self.visual_asset_ids or not self.visual_verified
        ):
            raise ValueError("Diagram questions need a reviewed, referenced visual asset")
        if self.type == QuestionType.data_interpretation and not self.data_table and not self.visual_asset_ids:
            raise ValueError("Data interpretation requires a table or reviewed visual")
        if self.visual_asset_ids and not self.visual_verified:
            raise ValueError("Every visual must be reviewed for accuracy")
        if self.answer.steps and sum(p.marks for p in self.answer.steps) != self.marks:
            raise ValueError("Worked solution steps must add to question marks")
        if self.answer.rubric and sum(p.marks for p in self.answer.rubric) != self.marks:
            raise ValueError("Rubric points must add to question marks")
        if not any((self.answer.correct_option_ids, self.answer.acceptable_answers,
                    self.answer.numeric_value is not None, self.answer.steps,
                    self.answer.rubric, self.matching_pairs)):
            raise ValueError("Every question must provide a marking answer")
        return self


class QuestionPublic(StrictModel):
    id: UUID
    question_id: UUID
    version: int
    status: Literal["draft", "approved", "retired"]
    type: QuestionType
    curriculum_id: UUID
    level_id: UUID
    subject_id: UUID
    topic_ids: list[UUID]
    outcome_ids: list[UUID]
    difficulty: Difficulty
    cognitive_target: str
    stem: str
    marks: int
    estimated_minutes: float
    options: list[Option]
    visual_asset_ids: list[UUID]
    latex: str | None
    data_table: list[dict[str, str | float | int]]
    provenance: str
    source_refs: list[SourceReference]


class SectionSpec(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    question_count: int = Field(ge=1, le=200)
    total_marks: int = Field(ge=1, le=500)
    question_types: list[QuestionType] = Field(min_length=1)


class AssessmentSpec(StrictModel):
    type: Literal["exam", "test", "quiz", "assignment", "worksheet", "revision"]
    title: str = Field(min_length=3, max_length=300)
    curriculum_id: UUID
    level_id: UUID
    subject_id: UUID
    topic_ids: list[UUID] = Field(min_length=1, max_length=50)
    outcome_ids: list[UUID] = Field(default_factory=list)
    term: str | None = Field(default=None, max_length=100)
    duration_minutes: int = Field(ge=5, le=600)
    total_marks: int = Field(ge=1, le=500)
    question_count: int = Field(ge=1, le=200)
    sections: list[SectionSpec] = Field(min_length=1)
    difficulty_mix: dict[Difficulty, int] = Field(default_factory=lambda: {
        Difficulty.easy: 30, Difficulty.medium: 50, Difficulty.hard: 20
    })
    topic_weights: dict[UUID, int] = Field(default_factory=dict)
    instructions: list[str] = Field(default_factory=list)
    school_name: str = Field(min_length=1, max_length=200)
    school_logo_asset_id: UUID | None = None

    @model_validator(mode="after")
    def verify_blueprint(self):
        if len(set(self.topic_ids)) != len(self.topic_ids):
            raise ValueError("Topics must be unique")
        if sum(s.question_count for s in self.sections) != self.question_count:
            raise ValueError("Section question counts do not match paper question count")
        if sum(s.total_marks for s in self.sections) != self.total_marks:
            raise ValueError("Section marks do not match paper total marks")
        if set(self.difficulty_mix) != set(Difficulty) or sum(self.difficulty_mix.values()) != 100 or any(v < 0 for v in self.difficulty_mix.values()):
            raise ValueError("Difficulty percentages must include easy, medium, hard and total 100")
        if self.topic_weights and (set(self.topic_weights) != set(self.topic_ids) or
                                   sum(self.topic_weights.values()) != 100 or
                                   any(v < 0 for v in self.topic_weights.values())):
            raise ValueError("Topic weights must cover all topics and total 100")
        return self


class AssembleRequest(StrictModel):
    spec: AssessmentSpec
    question_revision_ids: list[UUID] = Field(default_factory=list)
    variant_seed: int = Field(default=0, ge=0, le=2**31 - 1)


class ReviewDecision(StrictModel):
    notes: str = Field(default="", max_length=4000)


class ValidationReport(StrictModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    actual_marks: int
    estimated_minutes: float
    difficulty_marks: dict[str, int]
    topic_marks: dict[str, int]

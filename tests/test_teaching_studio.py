"""Local deterministic quality tests; no network, expensive AI or CI needed."""
import asyncio
from datetime import date
from uuid import UUID

import pytest
from pydantic import ValidationError

from services.ai.provider import AIResult
from services.templates.teaching.schemas import (
    BlockKind, CurriculumTarget, EvidenceBundle, EvidenceItem, LessonStage,
    SchemeWeek, TeachingBlock, TeachingBody, TeachingSection, TeachingSpec, TeachingType,
    TermCalendar,
)
from services.templates.teaching.service import TeachingGenerationError, TeachingStudio
from services.templates.teaching.templates import REQUIRED_SECTIONS
from services.validators.teaching import validate_teaching_document, validate_teaching_inputs

CID = UUID("00000000-0000-4000-8000-000000000001")
LID = UUID("00000000-0000-4000-8000-000000000002")
SID = UUID("00000000-0000-4000-8000-000000000003")
TID = UUID("00000000-0000-4000-8000-000000000004")
OID = UUID("00000000-0000-4000-8000-000000000005")
EID = UUID("00000000-0000-4000-8000-000000000006")
ASSET = UUID("00000000-0000-4000-8000-000000000007")
TENANT = UUID("00000000-0000-4000-8000-000000000008")
JOB = UUID("00000000-0000-4000-8000-000000000009")


def fixture(typ: TeachingType, *, subject="Primary Science"):
    spec = TeachingSpec(
        type=typ, curriculum_id=CID, curriculum_version="teacher-supplied-2026",
        level_id=LID, subject_id=SID, topic_ids=[TID], outcome_ids=[OID],
        country="UG", audience="teacher", depth="concise", term="Term 1",
        academic_year="2026", weeks=2, periods_per_week=5, period_minutes=40,
        calendar=TermCalendar(starts_on=date(2026, 2, 2), ends_on=date(2026, 2, 13)),
        lesson_date=date(2026, 2, 3), duration_minutes=40,
    )
    bundle = EvidenceBundle(
        curriculum_id=CID, curriculum_version=spec.curriculum_version,
        outcomes=[CurriculumTarget(
            id=OID, curriculum_id=CID, level_id=LID, subject_id=SID,
            topic_id=TID, code="SAMPLE-1", description="Describe water filtration",
        )],
        evidence=[EvidenceItem(
            id=EID, source_title="Authorized teacher sample (not official curriculum)",
            source_uri="fixture://teacher-supplied", license="CC0-1.0", page=1,
            excerpt="A filter can trap some suspended solids from water; filtration does not reliably remove all pathogens.",
            outcome_ids=[OID], asset_id=ASSET, asset_kind="diagram", asset_permission_verified=True,
        )],
    )
    sections = [TeachingSection(key=key, title=key.replace("_", " ").title(),
                blocks=[TeachingBlock(kind=BlockKind.paragraph,
                    text=f"{key}: Demonstrate filter use safely and discuss its limitations.",
                    citation_ids=[EID], outcome_ids=[OID])]) for key in REQUIRED_SECTIONS[typ]]
    body = TeachingBody(title=f"{subject}: water filtration", sections=sections)
    if typ == TeachingType.scheme_of_work:
        body.scheme_weeks = [SchemeWeek(
            week=w, topic_id=TID, subtopics=["Filtering materials"], outcome_ids=[OID],
            periods=2, methods=["group demonstration"], activities=["Compare filtered samples"],
            resources=["safe sample and sieve"], assessment="Explain filter limitations",
            citation_ids=[EID]) for w in (1, 2)]
    if typ == TeachingType.lesson_plan:
        body.lesson_stages = [LessonStage(
            key=key, minutes=mins, teacher_actions=["Model safe procedure"],
            learner_actions=["Explain observations"], assessment="Ask an oral question",
            differentiation="Allow a diagram description or spoken answer",
        ) for key, mins in (("introduction", 5), ("development", 20),
                            ("assessment", 10), ("conclusion", 5))]
    return spec, bundle, body


@pytest.mark.parametrize("typ", list(TeachingType))
def test_all_four_templates_have_mapped_outcomes(typ):
    spec, bundle, body = fixture(typ)
    result = validate_teaching_document(spec, bundle, body)
    assert result.valid, result.findings
    assert not result.missing_outcome_ids
    assert result.teacher_review_required


def test_math_native_equations_tables_and_diagram():
    spec, bundle, body = fixture(TeachingType.lesson_notes, subject="P5 Mathematics")
    bundle.outcomes[0].description = "Add whole numbers with counters"
    bundle.evidence[0].excerpt = "Two counters and three counters make five counters."
    for section in body.sections:
        section.blocks[0].text = "Model adding groups of counters; explain the steps."
    body.sections[4].blocks.extend([
        TeachingBlock(kind="equation", latex=r"2 + 3 = 5", citation_ids=[EID], outcome_ids=[OID]),
        TeachingBlock(kind="table", rows=[["n", "n+1"], ["2", "3"]],
                      citation_ids=[EID], outcome_ids=[OID]),
        TeachingBlock(kind="visual", asset_id=ASSET, caption="Licensed sample diagram",
                      citation_ids=[EID], outcome_ids=[OID]),
    ])
    bundle.required_visual_kinds = ["diagram"]
    assert validate_teaching_document(spec, bundle, body).valid
    body.sections[4].blocks[1].latex = "2 + 3 = 6"
    assert "math_inconsistent" in {f.code for f in validate_teaching_document(spec, bundle, body).findings}


def test_overallocated_scheme_flagged():
    spec, bundle, body = fixture(TeachingType.scheme_of_work)
    body.scheme_weeks[0].periods = 6
    assert "week_overallocated" in {f.code for f in validate_teaching_document(spec, bundle, body).findings}


def test_timed_lesson_flagged_when_minutes_incorrect():
    spec, bundle, body = fixture(TeachingType.lesson_plan)
    body.lesson_stages[0].minutes = 6
    assert "duration_mismatch" in {f.code for f in validate_teaching_document(spec, bundle, body).findings}


def test_unsupported_curriculum_rejected():
    spec, bundle, _ = fixture(TeachingType.teacher_guide)
    bundle.curriculum_version = "other-version"
    with pytest.raises(ValueError, match="unsupported curriculum"):
        validate_teaching_inputs(spec, bundle)


def test_incomplete_inputs_rejected():
    with pytest.raises(ValidationError):
        TeachingSpec(type="scheme_of_work", curriculum_id=CID, curriculum_version="v1",
                     level_id=LID, subject_id=SID, topic_ids=[TID], outcome_ids=[OID])
    with pytest.raises(ValidationError):
        TeachingBlock(kind="equation", text="2 + 3 = 5")


def test_ungrounded_citations_and_outcome_gaps():
    spec, bundle, body = fixture(TeachingType.teacher_guide)
    for section in body.sections:
        section.blocks[0].citation_ids = []
    review = validate_teaching_document(spec, bundle, body)
    assert not review.valid
    assert OID in review.missing_outcome_ids


class FakeProvider:
    def __init__(self, body):
        self.body = body

    async def generate(self, request):
        assert 'required_section_keys' in request.prompt
        return AIResult(text=self.body.model_dump_json(), provider="fixture", model="fake-test")


@pytest.mark.parametrize("typ", list(TeachingType))
def test_real_service_adapter_returns_core_generated_document(typ):
    spec, bundle, body = fixture(typ)
    result = asyncio.run(TeachingStudio(FakeProvider(body), "fake-test").generate(
        spec=spec, evidence=bundle, tenant_id=TENANT, generation_job_id=JOB))
    assert result.document["tenant_id"] == str(TENANT)
    assert result.document["body"]["schema_version"] == "teaching.v1"
    assert result.document["body"]["quality"]["valid"]
    assert result.document["body"]["reference_index"][0]["license"] == "CC0-1.0"


def test_malformed_ai_result_not_published():
    class BrokenProvider:
        async def generate(self, request):
            return AIResult(text="NOT JSON", provider="fixture", model="bad")
    spec, bundle, _ = fixture(TeachingType.lesson_notes)
    with pytest.raises(TeachingGenerationError):
        asyncio.run(TeachingStudio(BrokenProvider(), "bad").generate(
            spec=spec, evidence=bundle, tenant_id=TENANT, generation_job_id=JOB))

def test_ai_cannot_forge_approval_or_review_identity():
    spec, bundle, body = fixture(TeachingType.teacher_guide)
    body.review_status = "approved"
    body.reviewer_id = TENANT
    body.author_id = JOB
    body.revision = 999
    result = asyncio.run(TeachingStudio(FakeProvider(body), "fake-test").generate(
        spec=spec, evidence=bundle, tenant_id=TENANT, generation_job_id=JOB))
    assert result.document["body"]["review_status"] == "needs_review"
    assert result.document["body"]["reviewer_id"] is None
    assert result.document["body"]["author_id"] is None
    assert result.document["body"]["revision"] == 1


def test_visual_asset_requires_verified_use_permission():
    spec, bundle, body = fixture(TeachingType.lesson_notes)
    bundle.evidence[0].asset_permission_verified = False
    body.sections[4].blocks.append(TeachingBlock(
        kind="visual", asset_id=ASSET, citation_ids=[EID], outcome_ids=[OID]))
    assert "unlicensed_or_unknown_visual" in {
        finding.code for finding in validate_teaching_document(spec, bundle, body).findings
    }

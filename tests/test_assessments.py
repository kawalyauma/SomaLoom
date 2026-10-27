"""Agent 7 unit + authenticated integration tests (requires Agent 1 platform)."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.assessment.schemas import AssessmentSpec, QuestionDraft
from services.assessment.validation import calculate, fingerprint, validate_question_math


def ids():
    return {k: str(uuid4()) for k in ("curriculum", "level", "subject", "topic", "visual")}


def question(meta, kind="numerical"):
    common = {
        "curriculum_id": meta["curriculum"],
        "level_id": meta["level"],
        "subject_id": meta["subject"],
        "topic_ids": [meta["topic"]],
        "outcome_ids": [],
        "difficulty": "medium",
        "cognitive_target": "apply",
        "marks": 5,
        "estimated_minutes": 6,
        "source_refs": [],
        "provenance": "original",
    }
    if kind == "numerical":
        return {
            **common,
            "type": "numerical",
            "stem": "Calculate six times seven.",
            "answer": {
                "numeric_value": 42,
                "calculation": "6*7",
                "steps": [
                    {"criterion": "Multiply 6 by 7", "marks": 2},
                    {"criterion": "Obtain 42", "marks": 3},
                ],
            },
        }
    if kind == "multiple_choice":
        return {
            **common,
            "type": "multiple_choice",
            "stem": "Which of these is an even number?",
            "options": [{"id": "A", "text": "Three"}, {"id": "B", "text": "Four"}],
            "answer": {"correct_option_ids": ["B"], "explanation": "Four is divisible by two."},
        }
    if kind == "diagram_labeling":
        return {
            **common,
            "type": "diagram_labeling",
            "stem": "Label the referenced plant diagram.",
            "visual_asset_ids": [meta["visual"]],
            "visual_verified": True,
            "answer": {
                "acceptable_answers": ["root", "stem", "leaf"],
                "rubric": [
                    {"criterion": "Root", "marks": 2},
                    {"criterion": "Stem", "marks": 2},
                    {"criterion": "Leaf", "marks": 1},
                ],
            },
        }
    if kind == "matching":
        return {
            **common,
            "type": "matching",
            "stem": "Match each animal with its sound.",
            "matching_pairs": {"Dog": "Bark", "Cat": "Meow"},
            "answer": {"acceptable_answers": ["Dog–Bark", "Cat–Meow"]},
        }
    raise ValueError(kind)


def blueprint(meta, title="Term test", types=None, total=10, count=2, paper_type="test"):
    return {
        "type": paper_type,
        "title": title,
        "curriculum_id": meta["curriculum"],
        "level_id": meta["level"],
        "subject_id": meta["subject"],
        "topic_ids": [meta["topic"]],
        "school_name": "Synthetic School",
        "term": "Term II",
        "duration_minutes": 30,
        "total_marks": total,
        "question_count": count,
        "instructions": ["Answer every question."],
        "sections": [
            {
                "title": "Section A",
                "question_count": count,
                "total_marks": total,
                "question_types": types or ["numerical", "multiple_choice"],
            }
        ],
    }


def test_blueprint_rejects_wrong_section_marks():
    m = ids()
    with pytest.raises(ValidationError, match="Section marks"):
        payload = blueprint(m)
        payload["total_marks"] = 11
        AssessmentSpec.model_validate(payload)


def test_invalid_mcq_and_unreviewed_diagram():
    m = ids()
    bad = question(m, "multiple_choice")
    bad["options"][1]["text"] = "Three"
    with pytest.raises(ValidationError, match="distinct"):
        QuestionDraft.model_validate(bad)
    diagram = question(m, "diagram_labeling")
    diagram["visual_verified"] = False
    with pytest.raises(ValidationError, match="reviewed"):
        QuestionDraft.model_validate(diagram)


def test_arithmetic_expression_is_checked_without_eval():
    m = ids()
    q = QuestionDraft.model_validate(question(m))
    assert calculate("6*(3+4)") == 42
    assert not validate_question_math(q)
    q.answer.numeric_value = 43
    assert validate_question_math(q)
    with pytest.raises(ValueError):
        calculate("__import__('os').system('whoami')")
    with pytest.raises(ValueError):
        calculate("2**100000")


def test_case_insensitive_duplicate_fingerprint():
    m = ids()
    first = QuestionDraft.model_validate(question(m))
    second = QuestionDraft.model_validate(
        {**question(m), "stem": "  CALCULATE six   times seven. "}
    )
    assert fingerprint(first) == fingerprint(second)


@pytest.fixture
def api(client):
    client.headers.update({"Origin": "http://localhost:3000"})
    return client


def login(api, i=0, role="teacher"):
    from conftest import sign_in

    assert sign_in(api, f"{role}{i}@example.org").status_code == 200


def create_approved(api, m, kind="numerical"):
    q = api.post("/api/v1/question-bank", json=question(m, kind))
    assert q.status_code == 201, q.text
    root = q.json()["question_id"]
    login(api, role="reviewer")
    approved = api.post(f"/api/v1/question-bank/{root}/approve")
    assert approved.status_code == 200, approved.text
    login(api)
    return approved.json()


def test_login_required_and_teacher_cannot_approve(api, accounts):
    m = ids()
    assert api.get("/api/v1/question-bank").status_code == 401
    login(api)
    row = api.post("/api/v1/question-bank", json=question(m)).json()
    assert api.post(f"/api/v1/question-bank/{row['question_id']}/approve").status_code == 403


def test_duplicate_and_versioning(api, accounts):
    m = ids()
    login(api)
    a = api.post("/api/v1/question-bank", json=question(m))
    assert a.status_code == 201, a.text
    assert api.post("/api/v1/question-bank", json=question(m)).status_code == 409
    changed = question(m)
    changed["stem"] = "Determine the product of six and seven."
    root = a.json()["question_id"]
    b = api.post(f"/api/v1/question-bank/{root}/revisions", json=changed)
    assert b.status_code == 201, b.text
    assert b.json()["version"] == 2
    history = api.get(f"/api/v1/question-bank/{root}/versions")
    assert len(history.json()) == 2


def test_exam_student_separation_and_publication(api, accounts):
    m = ids()
    login(api)
    q1 = create_approved(api, m, "numerical")
    second = question(m, "multiple_choice")
    second["difficulty"] = "easy"
    b = api.post("/api/v1/question-bank", json=second)
    assert b.status_code == 201, b.text
    login(api, role="reviewer")
    api.post(f"/api/v1/question-bank/{b.json()['question_id']}/approve")
    login(api)
    exam = blueprint(m, title="End of Term Exam", paper_type="exam")
    body = {"spec": exam, "question_revision_ids": [q1["id"], b.json()["id"]]}
    r = api.post("/api/v1/assessments", json=body)
    assert r.status_code == 201, r.text
    paper_id = r.json()["id"]
    student = api.get(f"/api/v1/assessments/{paper_id}/student-paper")
    guide = api.get(f"/api/v1/assessments/{paper_id}/marking-guide")
    assert student.status_code == 200
    assert student.json()["audience"] == "student"
    assert '"answer":' not in student.text
    assert guide.json()["audience"] == "teacher"
    assert '"correct_option_ids"' in guide.text
    assert student.json()["total_marks"] == guide.json()["total_marks"] == 10
    assert api.post(f"/api/v1/assessments/{paper_id}/publish", json={}).status_code == 403
    login(api, role="reviewer")
    pub = api.post(f"/api/v1/assessments/{paper_id}/publish", json={"notes": "Reviewed"})
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "published"


def test_generation_variants_quiz_and_short_test(api, accounts):
    m = ids()
    login(api)
    create_approved(api, m)
    q = question(m, "multiple_choice")
    q["stem"] = "Which listed number is divisible by two?"
    r = api.post("/api/v1/question-bank", json=q)
    login(api, role="reviewer")
    api.post(f"/api/v1/question-bank/{r.json()['question_id']}/approve")
    login(api)
    quiz = blueprint(m, title="Topic quiz", paper_type="quiz")
    assembled = api.post("/api/v1/assessments/generate", json={"spec": quiz, "variant_seed": 12})
    assert assembled.status_code == 201, assembled.text
    test = blueprint(m, title="Class test")
    assembled = api.post("/api/v1/assessments/generate", json={"spec": test, "variant_seed": 13})
    assert assembled.status_code == 201, assembled.text


def test_invalid_marks_and_mathematics_are_rejected(api, accounts):
    m = ids()
    login(api)
    bad = question(m)
    bad["answer"]["numeric_value"] = 999
    assert api.post("/api/v1/question-bank", json=bad).status_code == 422
    a = create_approved(api, m)
    wrong = blueprint(m, total=10)
    request = {"spec": wrong, "question_revision_ids": [a["id"], a["id"]]}
    assert api.post("/api/v1/assessments", json=request).status_code == 422


def test_matching_does_not_leak_pairs(api, accounts):
    m = ids()
    login(api)
    question_row = api.post("/api/v1/question-bank", json=question(m, "matching"))
    assert question_row.status_code == 201
    assert "matching_pairs" not in question_row.json()
    login(api, role="reviewer")
    api.post(f"/api/v1/question-bank/{question_row.json()['question_id']}/approve")
    login(api)
    spec = blueprint(
        m, title="Matching task", types=["matching"], total=5, count=1, paper_type="worksheet"
    )
    r = api.post(
        "/api/v1/assessments",
        json={"spec": spec, "question_revision_ids": [question_row.json()["id"]]},
    )
    assert r.status_code == 201, r.text
    content = api.get(f"/api/v1/assessments/{r.json()['id']}/student-paper").json()
    item = content["sections"][0]["questions"][0]
    assert "matching_pairs" not in item
    assert sorted(item["matching_left"]) == ["Cat", "Dog"]
    assert sorted(item["matching_right"]) == ["Bark", "Meow"]


def seed_visual(db, tenant_id):
    from app.core.models import BackgroundJob, extractions, resource_versions, resources, visuals

    job = BackgroundJob(tenant_id=tenant_id, kind="extraction")
    db.add(job)
    db.flush()
    resource_id, version_id, extraction_id, visual_id = (uuid4() for _ in range(4))
    provenance = {
        "source_uri": "synthetic://test-diagram",
        "license": "CC0",
        "checksum_sha256": "0" * 64,
    }
    db.execute(
        resources.insert().values(
            id=resource_id,
            tenant_id=tenant_id,
            title="Synthetic plant diagram",
            media_type="image/png",
            provenance=provenance,
        )
    )
    db.execute(
        resource_versions.insert().values(
            id=version_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            version=1,
            object_key="synthetic/plant.png",
            checksum_sha256="0" * 64,
            provenance=provenance,
        )
    )
    db.execute(
        extractions.insert().values(
            id=extraction_id,
            tenant_id=tenant_id,
            resource_version_id=version_id,
            job_id=job.id,
            engine="synthetic-test",
        )
    )
    db.execute(
        visuals.insert().values(
            id=visual_id,
            tenant_id=tenant_id,
            extraction_id=extraction_id,
            object_key="synthetic/plant.png",
            kind="diagram",
            page=1,
            caption="Synthetic reviewed plant",
            provenance=provenance,
        )
    )
    db.commit()
    return visual_id


def test_verified_diagram_question(api, accounts, db):
    m = ids()
    login(api)
    assert (
        api.post("/api/v1/question-bank", json=question(m, "diagram_labeling")).status_code == 422
    )
    m["visual"] = str(seed_visual(db, accounts[0][0].id))
    r = api.post("/api/v1/question-bank", json=question(m, "diagram_labeling"))
    assert r.status_code == 201, r.text
    login(api, role="reviewer")
    api.post(f"/api/v1/question-bank/{r.json()['question_id']}/approve")
    login(api)
    spec = blueprint(m, title="Diagram assessment", types=["diagram_labeling"], total=5, count=1)
    paper = api.post(
        "/api/v1/assessments", json={"spec": spec, "question_revision_ids": [r.json()["id"]]}
    )
    assert paper.status_code == 201, paper.text


def test_cross_tenant_objects_are_inaccessible(api, accounts):
    m = ids()
    login(api)
    q = create_approved(api, m)
    spec = blueprint(m, count=1, total=5, types=["numerical"])
    result = api.post(
        "/api/v1/assessments", json={"spec": spec, "question_revision_ids": [q["id"]]}
    )
    assert result.status_code == 201, result.text
    paper_id = result.json()["id"]
    login(api, i=1)
    assert api.get(f"/api/v1/question-bank/{q['question_id']}").status_code == 404
    assert api.get(f"/api/v1/assessments/{paper_id}/marking-guide").status_code == 404
    assert api.get(f"/api/v1/assessments/{paper_id}/student-paper").status_code == 404

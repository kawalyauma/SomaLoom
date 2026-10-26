"""Tenant-scoped assessment API. Register this router with Agent 1's app composition."""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.router import audit
from app.auth.security import require_roles
from app.core.database import get_db
from app.core.models import User
from contracts.v1.schemas import Page
from services.assessment.documents import student_document, teacher_guide
from services.assessment.generation import assemble_sections, select_revisions
from services.assessment.models import papers, question_versions, utcnow
from services.assessment.schemas import (
    AssembleRequest, AssessmentSpec, Difficulty, QuestionDraft, QuestionPublic,
    ReviewDecision,
)
from services.assessment.validation import fingerprint, validate_paper, validate_question_math

router = APIRouter(tags=["assessments"])

READ = Depends(require_roles("school_admin", "teacher", "reviewer"))
WRITE = Depends(require_roles("school_admin", "teacher"))
REVIEW = Depends(require_roles("school_admin", "reviewer"))


def latest(db: Session, tenant_id: UUID, question_id: UUID):
    return db.execute(select(question_versions).where(
        question_versions.c.tenant_id == tenant_id,
        question_versions.c.question_id == question_id
    ).order_by(question_versions.c.version.desc()).limit(1)).mappings().first()


def question_view(row):
    data = row["payload"]
    visible = {key: data[key] for key in QuestionPublic.model_fields
               if key in data and key not in ("id", "question_id", "status", "version")}
    return QuestionPublic(id=row["id"], question_id=row["question_id"],
                          version=row["version"], status=row["status"], **visible)


def ensure_distinct(db, tenant_id, question: QuestionDraft, ignore=None):
    fpr = fingerprint(question)
    stmt = select(question_versions.c.question_id).where(
        question_versions.c.tenant_id == tenant_id,
        question_versions.c.fingerprint == fpr,
        question_versions.c.status != "retired",
    )
    if ignore is not None:
        stmt = stmt.where(question_versions.c.question_id != ignore)
    if db.execute(stmt.limit(1)).first():
        raise HTTPException(409, "A matching question already exists in this school")
    problems = validate_question_math(question)
    if problems:
        raise HTTPException(422, "; ".join(problems))
    return fpr


def get_paper(db, tenant_id: UUID, paper_id: UUID):
    result = db.execute(select(papers).where(
        papers.c.tenant_id == tenant_id, papers.c.id == paper_id)).mappings().first()
    if result is None:
        raise HTTPException(404, "Assessment not found")
    return result


@router.post("/question-bank", response_model=QuestionPublic, status_code=201)
def create_question(
    data: QuestionDraft, request: Request, user: User = WRITE,
    db: Session = Depends(get_db),
):
    fpr = ensure_distinct(db, user.tenant_id, data)
    row_id, root_id = uuid4(), uuid4()
    db.execute(question_versions.insert().values(
        id=row_id, question_id=root_id, tenant_id=user.tenant_id, version=1,
        status="draft", fingerprint=fpr, payload=data.model_dump(mode="json")))
    audit(db, user, "assessment.question_created", root_id, request)
    db.commit()
    return question_view(latest(db, user.tenant_id, root_id))


@router.get("/question-bank", response_model=Page[QuestionPublic])
def list_questions(
    subject_id: UUID | None = None, topic_id: UUID | None = None,
    difficulty: Difficulty | None = None, status: str | None = Query(None, pattern="^(draft|approved|retired)$"),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    user: User = READ, db: Session = Depends(get_db),
):
    # Query the school first; only the latest revision of each question is shown.
    rows = db.execute(select(question_versions).where(
        question_versions.c.tenant_id == user.tenant_id
    ).order_by(question_versions.c.question_id, question_versions.c.version.desc())).mappings()
    newest = {}
    for row in rows:
        newest.setdefault(row["question_id"], row)
    filtered = [
        question_view(r) for r in newest.values()
        if (status is None or r["status"] == status)
        and (subject_id is None or r["payload"]["subject_id"] == str(subject_id))
        and (topic_id is None or str(topic_id) in r["payload"]["topic_ids"])
        and (difficulty is None or r["payload"]["difficulty"] == difficulty)
    ]
    filtered.sort(key=lambda x: (x.stem.casefold(), str(x.question_id)))
    return {"items": filtered[(page-1)*page_size:page*page_size],
            "page": page, "page_size": page_size, "total": len(filtered)}


@router.get("/question-bank/{question_id}", response_model=QuestionPublic)
def get_question(question_id: UUID, user: User = READ, db: Session = Depends(get_db)):
    row = latest(db, user.tenant_id, question_id)
    if row is None:
        raise HTTPException(404, "Question not found")
    return question_view(row)


@router.get("/question-bank/{question_id}/versions", response_model=list[QuestionPublic])
def question_history(question_id: UUID, user: User = READ, db: Session = Depends(get_db)):
    rows = db.execute(select(question_versions).where(
        question_versions.c.tenant_id == user.tenant_id,
        question_versions.c.question_id == question_id
    ).order_by(question_versions.c.version)).mappings().all()
    if not rows:
        raise HTTPException(404, "Question not found")
    return [question_view(x) for x in rows]


@router.get("/question-bank/{question_id}/marking-answer")
def bank_marking_answer(
    question_id: UUID,
    user: User = READ, db: Session = Depends(get_db),
):
    row = latest(db, user.tenant_id, question_id)
    if row is None:
        raise HTTPException(404, "Question not found")
    return {"question_id": str(row["question_id"]), "version": row["version"],
            "marks": row["payload"]["marks"], "answer": row["payload"]["answer"],
            "matching_pairs": row["payload"]["matching_pairs"]}


@router.post("/question-bank/{question_id}/revisions",
             response_model=QuestionPublic, status_code=201)
def revise_question(
    question_id: UUID, data: QuestionDraft, request: Request,
    user: User = WRITE, db: Session = Depends(get_db),
):
    row = latest(db, user.tenant_id, question_id)
    if row is None:
        raise HTTPException(404, "Question not found")
    fpr = ensure_distinct(db, user.tenant_id, data, ignore=question_id)
    db.execute(question_versions.insert().values(
        id=uuid4(), question_id=question_id, tenant_id=user.tenant_id,
        version=row["version"] + 1, status="draft", fingerprint=fpr,
        payload=data.model_dump(mode="json")))
    audit(db, user, "assessment.question_revised", question_id, request)
    db.commit()
    return question_view(latest(db, user.tenant_id, question_id))


@router.post("/question-bank/{question_id}/approve", response_model=QuestionPublic)
def approve_question(
    question_id: UUID, request: Request, user: User = REVIEW,
    db: Session = Depends(get_db),
):
    row = latest(db, user.tenant_id, question_id)
    if row is None:
        raise HTTPException(404, "Question not found")
    if row["status"] == "retired":
        raise HTTPException(409, "Retired revision cannot be approved")
    db.execute(question_versions.update().where(
        question_versions.c.tenant_id == user.tenant_id,
        question_versions.c.question_id == question_id,
        question_versions.c.id != row["id"],
        question_versions.c.status == "approved",
    ).values(status="retired"))
    db.execute(question_versions.update().where(
        question_versions.c.id == row["id"], question_versions.c.tenant_id == user.tenant_id
    ).values(status="approved"))
    audit(db, user, "assessment.question_approved", question_id, request)
    db.commit()
    return question_view(latest(db, user.tenant_id, question_id))


@router.post("/question-bank/{question_id}/retire", response_model=QuestionPublic)
def retire_question(
    question_id: UUID, request: Request, user: User = REVIEW,
    db: Session = Depends(get_db),
):
    row = latest(db, user.tenant_id, question_id)
    if row is None:
        raise HTTPException(404, "Question not found")
    db.execute(question_versions.update().where(
        question_versions.c.tenant_id == user.tenant_id,
        question_versions.c.question_id == question_id,
    ).values(status="retired"))
    audit(db, user, "assessment.question_retired", question_id, request)
    db.commit()
    return question_view(latest(db, user.tenant_id, question_id))


def create_paper(
    data: AssembleRequest, request: Request, user: User, db: Session,
):
    pool = select_revisions(db, user.tenant_id, data.spec,
                            data.question_revision_ids, data.variant_seed)
    sections = assemble_sections(data.spec, pool, bool(data.question_revision_ids))
    report = validate_paper(data.spec, sections)
    if not report.valid:
        raise HTTPException(422, {"validation_errors": report.errors,
                                  "warnings": report.warnings})
    paper_id = uuid4()
    db.execute(papers.insert().values(
        id=paper_id, tenant_id=user.tenant_id, status="draft",
        spec=data.spec.model_dump(mode="json"), sections=sections))
    audit(db, user, "assessment.created", paper_id, request)
    db.commit()
    return {"id": paper_id, "status": "draft", "validation": report}


@router.post("/assessments", status_code=201)
def create_assessment(
    data: AssembleRequest, request: Request,
    user: User = WRITE, db: Session = Depends(get_db),
):
    if not data.question_revision_ids:
        raise HTTPException(422, "Use /assessments/generate for bank-selected questions")
    return create_paper(data, request, user, db)


@router.post("/assessments/generate", status_code=201)
def generate_from_bank(
    data: AssembleRequest, request: Request,
    user: User = WRITE, db: Session = Depends(get_db),
):
    if data.question_revision_ids:
        raise HTTPException(422, "Remove manual revision IDs when generating variants")
    return create_paper(data, request, user, db)


@router.get("/assessments", response_model=Page[dict])
def list_assessments(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    user: User = READ, db: Session = Depends(get_db),
):
    query = select(papers).where(papers.c.tenant_id == user.tenant_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    records = db.execute(query.order_by(papers.c.created_at.desc())
                         .offset((page-1)*page_size).limit(page_size)).mappings().all()
    return {"items": [
        {"id": str(r["id"]), "status": r["status"], "title": r["spec"]["title"],
         "type": r["spec"]["type"], "total_marks": r["spec"]["total_marks"]}
        for r in records
    ], "page": page, "page_size": page_size, "total": total}


@router.get("/assessments/{assessment_id}")
def get_assessment(
    assessment_id: UUID, user: User = READ, db: Session = Depends(get_db),
):
    r = get_paper(db, user.tenant_id, assessment_id)
    return {"id": str(r["id"]), "status": r["status"], "spec": r["spec"],
            "student_document": student_document(AssessmentSpec.model_validate(r["spec"]), r["sections"])}


@router.get("/assessments/{assessment_id}/student-paper")
def learner_paper(
    assessment_id: UUID, user: User = READ, db: Session = Depends(get_db),
):
    r = get_paper(db, user.tenant_id, assessment_id)
    return student_document(AssessmentSpec.model_validate(r["spec"]), r["sections"])


@router.get("/assessments/{assessment_id}/marking-guide")
def marking_guide(
    assessment_id: UUID, user: User = READ, db: Session = Depends(get_db),
):
    r = get_paper(db, user.tenant_id, assessment_id)
    return teacher_guide(AssessmentSpec.model_validate(r["spec"]), r["sections"])


@router.get("/assessments/{assessment_id}/validate")
def validation_details(
    assessment_id: UUID, user: User = READ, db: Session = Depends(get_db),
):
    r = get_paper(db, user.tenant_id, assessment_id)
    return validate_paper(AssessmentSpec.model_validate(r["spec"]), r["sections"])


@router.post("/assessments/{assessment_id}/publish")
def publish_assessment(
    assessment_id: UUID, data: ReviewDecision, request: Request,
    user: User = REVIEW, db: Session = Depends(get_db),
):
    r = get_paper(db, user.tenant_id, assessment_id)
    if r["status"] != "draft":
        raise HTTPException(409, "Assessment has already been published")
    spec = AssessmentSpec.model_validate(r["spec"])
    report = validate_paper(spec, r["sections"])
    if not report.valid:
        raise HTTPException(422, {"validation_errors": report.errors})
    ids = {UUID(q["id"]) for section in r["sections"] for q in section["questions"]}
    current = db.execute(select(question_versions.c.id).where(
        question_versions.c.tenant_id == user.tenant_id,
        question_versions.c.id.in_(ids),
        question_versions.c.status == "approved")).scalars().all()
    if len(current) != len(ids):
        raise HTTPException(409, "A question revision has been retired or lost approval")
    db.execute(papers.update().where(
        papers.c.id == assessment_id, papers.c.tenant_id == user.tenant_id
    ).values(status="published", reviewer_id=user.id, review_notes=data.notes,
             published_at=utcnow()))
    audit(db, user, "assessment.published", assessment_id, request)
    db.commit()
    return {"id": assessment_id, "status": "published", "validation": report}

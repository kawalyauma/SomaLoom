"""Curriculum hierarchy API. Explicit approval is required for official claims."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.auth.security import current_user, require_roles
from app.auth.router import audit
from app.core.database import get_db
from app.core.models import User, curricula, outcomes
from services.curriculum.models import topics, mappings

router = APIRouter(tags=["curriculum"])

def tenant(user: User) -> UUID:
    if user.tenant_id is None:
        raise HTTPException(403, "Select a school account; platform-wide access is not implicit")
    return user.tenant_id

def scoped(db, table, id, school):
    row = db.execute(select(table).where(table.c.id == id, table.c.tenant_id == school)).mappings().first()
    if not row:
        raise HTTPException(404, "Not found")
    return row

def page_result(db, statement, page, page_size):
    rows = db.execute(statement.offset((page - 1) * page_size).limit(page_size)).mappings().all()
    # Count the unpaginated statement, including filters.
    count = db.scalar(select(func.count()).select_from(statement.subquery()))
    return {"items": [dict(r) for r in rows], "page": page, "page_size": page_size, "total": count}

@router.get("/curricula")
def browse_curricula(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    school = tenant(user)
    return page_result(db, select(curricula).where(curricula.c.tenant_id == school).order_by(curricula.c.name), page, page_size)

@router.get("/curricula/{curriculum_id}/topics")
def browse_topics(curriculum_id: UUID, grade: str | None = None, subject: str | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    school = tenant(user)
    scoped(db, curricula, curriculum_id, school)
    stmt = select(topics).where(topics.c.tenant_id == school, topics.c.curriculum_id == curriculum_id)
    if grade:
        stmt = stmt.where(topics.c.grade == grade)
    if subject:
        stmt = stmt.where(topics.c.subject == subject)
    return page_result(db, stmt.order_by(topics.c.sequence, topics.c.id), page, page_size)

@router.get("/topics/{topic_id}/outcomes")
def topic_outcomes(topic_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    school = tenant(user)
    scoped(db, topics, topic_id, school)
    rows = db.execute(select(mappings, outcomes.c.code, outcomes.c.description)
        .join(outcomes, (outcomes.c.id == mappings.c.outcome_id) & (outcomes.c.tenant_id == mappings.c.tenant_id))
        .where(mappings.c.tenant_id == school, mappings.c.topic_id == topic_id)
        .order_by(outcomes.c.code)).mappings().all()
    return {"items": [{**dict(row), "official": row["origin"] == "official_candidate" and
             row["review_status"] == "approved" and bool(row["source_uri"])} for row in rows],
            "page": 1, "page_size": max(1, len(rows)), "total": len(rows)}

class TopicInput(BaseModel):
    level: str = Field(min_length=1, max_length=80)
    grade: str = Field(min_length=1, max_length=80)
    subject: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    kind: str = Field(pattern="^(unit|topic|subtopic)$")
    parent_id: UUID | None = None
    term: int | None = Field(default=None, ge=1, le=4)
    week: int | None = Field(default=None, ge=1, le=53)
    sequence: int = Field(default=0, ge=0)
    prerequisites: list[UUID] = Field(default_factory=list)
    source_uri: str | None = None
    source_license: str | None = None

@router.post("/curricula/{curriculum_id}/topics", status_code=201)
def create_topic(curriculum_id: UUID, data: TopicInput, request: Request,
                 user: User = Depends(require_roles("school_admin")),
                 db: Session = Depends(get_db)):
    school = tenant(user)
    scoped(db, curricula, curriculum_id, school)
    if data.parent_id:
        parent = scoped(db, topics, data.parent_id, school)
        if parent["curriculum_id"] != curriculum_id:
            raise HTTPException(422, "Parent belongs to a different curriculum")
    for prerequisite in data.prerequisites:
        related = scoped(db, topics, prerequisite, school)
        if related["curriculum_id"] != curriculum_id:
            raise HTTPException(422, "Prerequisite belongs to a different curriculum")
    values = data.model_dump()
    values.update(tenant_id=school, curriculum_id=curriculum_id)
    row = db.execute(topics.insert().values(**values).returning(topics.c.id)).scalar_one()
    audit(db, user, "curriculum.topic.create", row, request)
    db.commit()
    return {"id": row}

class OutcomeInput(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    required: bool = True
    origin: str = Field(pattern="^(official_candidate|enrichment)$")
    source_uri: str | None = None
    source_license: str | None = None
    concepts: list[str] = Field(default_factory=list, max_length=30)

@router.post("/topics/{topic_id}/outcomes", status_code=201)
def add_outcome(topic_id: UUID, data: OutcomeInput, request: Request,
                user: User = Depends(require_roles("school_admin")),
                db: Session = Depends(get_db)):
    school = tenant(user)
    topic = scoped(db, topics, topic_id, school)
    if data.origin == "official_candidate" and (not data.source_uri or not data.source_license):
        raise HTTPException(422, "Official candidates require a source URI and license")
    oid = db.execute(outcomes.insert().values(tenant_id=school, curriculum_id=topic["curriculum_id"],
        code=data.code, description=data.description).returning(outcomes.c.id)).scalar_one()
    mid = db.execute(mappings.insert().values(tenant_id=school, topic_id=topic_id,
        outcome_id=oid, required=int(data.required), origin=data.origin, review_status="draft",
        source_uri=data.source_uri, source_license=data.source_license, concepts=data.concepts,
        revision=1).returning(mappings.c.id)).scalar_one()
    audit(db, user, "curriculum.outcome.create", mid, request)
    db.commit()
    return {"id": mid, "outcome_id": oid, "review_status": "draft", "official": False}

class ReviewInput(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")

@router.post("/topics/{topic_id}/mappings/{mapping_id}/review")
def review_mapping(topic_id: UUID, mapping_id: UUID, data: ReviewInput, request: Request,
                   user: User = Depends(require_roles("reviewer", "school_admin")),
                   db: Session = Depends(get_db)):
    school = tenant(user)
    scoped(db, topics, topic_id, school)
    mapping = scoped(db, mappings, mapping_id, school)
    if mapping["topic_id"] != topic_id:
        raise HTTPException(404, "Not found")
    if data.status == "approved" and mapping["origin"] == "official_candidate" and (
        not mapping["source_uri"] or not mapping["source_license"]
    ):
        raise HTTPException(422, "Provenance required")
    db.execute(mappings.update().where(mappings.c.id == mapping_id,
        mappings.c.tenant_id == school).values(review_status=data.status,
        reviewed_by=user.id, revision=mapping["revision"] + 1))
    # Related previously-approved research is stale after a mapping change.
    from services.knowledge.models import research_records
    db.execute(research_records.update().where(research_records.c.tenant_id == school,
        research_records.c.topic_id == topic_id).values(review_status="stale"))
    audit(db, user, "curriculum.mapping.review", mapping_id, request)
    db.commit()
    return {"id": mapping_id, "review_status": data.status,
            "official": data.status == "approved" and mapping["origin"] == "official_candidate"}

"""Authenticated feature router; Agent 1 registers it with prefix /api/v1."""
import os
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth.router import audit
from app.auth.security import current_user, require_roles
from app.core.database import get_db
from app.core.models import BackgroundJob, User, resource_versions
from services.curriculum.models import topics
from services.knowledge.embeddings import Embeddings
from services.knowledge.models import research_records
from services.knowledge.research import dispatch_pending, submit
from services.knowledge.retrieval import lookup, search

router = APIRouter(tags=["knowledge"])

def school_of(user: User) -> UUID:
    if user.tenant_id is None:
        raise HTTPException(403, "Use a school-scoped account")
    return user.tenant_id

def topic_or_404(db, school, topic_id):
    row = db.execute(select(topics).where(topics.c.id == topic_id,
                            topics.c.tenant_id == school)).mappings().first()
    if row is None:
        raise HTTPException(404, "Topic not found")
    return row

class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    topic_id: UUID | None = None
    tenant_id: UUID | None = None  # Compatibility only: never grants access.
    filters: dict = Field(default_factory=dict)
    k: int = Field(default=10, ge=1, le=50)

@router.post("/search")
def hybrid_search(data: SearchInput, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    school = school_of(user)
    if data.tenant_id is not None and data.tenant_id != school:
        raise HTTPException(404, "School not found")
    filters = dict(data.filters)
    if data.topic_id:
        topic = topic_or_404(db, school, data.topic_id)
        filters.update(grade=topic["grade"], subject=topic["subject"])
    try:
        embedded = os.environ.get("SOMALOOM_EMBEDDINGS") == "openai"
        results = search(db, school, data.query, filters=filters, limit=data.k,
                         embedder=Embeddings() if embedded else None)
    except RuntimeError as exc:
        raise HTTPException(503, "Embedding provider unavailable") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"items": results, "total": len(results), "page": 1, "page_size": data.k,
            "retrieval_mode": "hybrid" if embedded else "keyword",
            "semantic_available": embedded}

@router.get("/citations/{item_id}")
def citation(item_id: UUID, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    ev = lookup(db, school_of(user), item_id)
    if not ev:
        raise HTTPException(404, "Evidence not found")
    return ev

class ResearchInput(BaseModel):
    topic_id: UUID

def kick_dispatch(db, school):
    # The database outbox is durable even if Redis is temporarily unavailable.
    try:
        dispatch_pending(db, school)
    except Exception:
        db.rollback()

@router.post("/research/jobs", status_code=202)
def research_job(data: ResearchInput, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    school = school_of(user)
    topic_or_404(db, school, data.topic_id)
    id_ = submit(db, school, user.id, "topic_research", {"topic_id": str(data.topic_id)})
    kick_dispatch(db, school)
    return {"id": id_, "status": "queued", "progress": 0}

@router.get("/research/jobs/{job_id}")
def job_status(job_id: UUID, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    job = db.execute(select(BackgroundJob).where(BackgroundJob.id == job_id,
        BackgroundJob.tenant_id == school_of(user),
        BackgroundJob.kind.in_(["topic_research", "knowledge_reindex"]))).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    return {"id": job.id, "status": job.status, "progress": job.progress,
            "error": job.error, "created_at": job.created_at, "finished_at": job.finished_at}

@router.get("/research/bundles/{record_id}")
def bundle(record_id: UUID, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    row = db.execute(select(research_records).where(
        research_records.c.id == record_id,
        research_records.c.tenant_id == school_of(user))).mappings().first()
    if not row:
        raise HTTPException(404, "Research not found")
    if row["review_status"] == "stale":
        raise HTTPException(409, "Research stale; regenerate to refresh source citations")
    return {"id": str(row["id"]), **row["bundle"], "review_status": row["review_status"],
            "content_version": row["content_version"]}

@router.get("/topics/{topic_id}/coverage")
def coverage(topic_id: UUID, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    school = school_of(user)
    topic_or_404(db, school, topic_id)
    row = db.execute(select(research_records).where(
        research_records.c.tenant_id == school,
        research_records.c.topic_id == topic_id)
        .order_by(research_records.c.content_version.desc())).mappings().first()
    if not row:
        return {"topic_id": str(topic_id), "status": "not_researched",
                "coverage": [], "gaps": [], "conflicts": []}
    return {"topic_id": str(topic_id), "status": row["review_status"],
            "record_id": str(row["id"]), "coverage": row["bundle"]["coverage"],
            "gaps": row["bundle"]["gaps"], "conflicts": row["bundle"]["conflicts"],
            "confidence": row["bundle"]["confidence"]}

class ResearchReview(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    conflicts_acknowledged: bool = False

@router.post("/research/bundles/{record_id}/review")
def review_bundle(record_id: UUID, data: ResearchReview, request: Request,
                  user: User = Depends(require_roles("school_admin", "reviewer")),
                  db: Session = Depends(get_db)):
    school = school_of(user)
    row = db.execute(select(research_records).where(research_records.c.id == record_id,
                 research_records.c.tenant_id == school)).mappings().first()
    if not row:
        raise HTTPException(404, "Not found")
    if row["review_status"] == "stale":
        raise HTTPException(409, "Research is stale; rerun before approval")
    if data.status == "approved" and row["bundle"].get("conflicts") and not data.conflicts_acknowledged:
        raise HTTPException(409, "Potential conflicts require explicit reviewer acknowledgement")
    new_bundle = {**row["bundle"], "review_status": data.status}
    db.execute(research_records.update().where(research_records.c.id == record_id,
               research_records.c.tenant_id == school).values(
                   review_status=data.status, bundle=new_bundle))
    audit(db, user, "research.review", record_id, request)
    db.commit()
    return {"id": record_id, "review_status": data.status}

@router.post("/index/resource-versions/{version_id}", status_code=202)
def reindex(version_id: UUID, user: User = Depends(require_roles("school_admin")),
            db: Session = Depends(get_db)):
    school = school_of(user)
    available = db.execute(select(resource_versions.c.id).where(
        resource_versions.c.id == version_id,
        resource_versions.c.tenant_id == school)).scalar_one_or_none()
    if not available:
        raise HTTPException(404, "Resource version not found")
    job_id = submit(db, school, user.id, "knowledge_reindex",
                    {"resource_version_id": str(version_id)})
    kick_dispatch(db, school)
    return {"id": job_id, "status": "queued", "progress": 0}

@router.post("/research/dispatch")
def dispatch(user: User = Depends(require_roles("school_admin")),
             db: Session = Depends(get_db)):
    try:
        count = dispatch_pending(db, school_of(user))
    except Exception as exc:
        db.rollback()
        raise HTTPException(503, "Queue unavailable; persisted jobs will be retried") from exc
    return {"dispatched": count}

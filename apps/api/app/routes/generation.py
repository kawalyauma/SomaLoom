"""Authenticated tenant-isolated generation endpoints; no prompt code execution."""

from __future__ import annotations

import re
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Response, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import current_user, require_roles
from app.core.config import get_settings
from app.core.database import get_db
from app.core.models import BackgroundJob, User, generations, documents
from services.ai.provider import provider_available
from services.generation.repository import (
    create_record,
    draft_record,
    owned_record,
)
from services.curriculum.models import mappings, topics
from app.core.models import curricula
from services.generation.schema import DocumentKind, GenerationInput, GenerationStatus
from services.generation.tasks import enqueue_generation

router = APIRouter(prefix="/generations", tags=["generations"])


def tenant(user: User) -> UUID:
    if user.tenant_id is None:
        # Platform admin must authenticate as a tenant member; never use a client-provided tenant.
        raise HTTPException(403, "School membership required")
    return user.tenant_id


def _status(db: Session, generation_id: UUID, user: User) -> GenerationStatus:
    record = owned_record(db, generation_id, tenant(user))
    if not record:
        raise HTTPException(404, "Generation not found")
    doc = draft_record(db, generation_id, tenant(user))
    return GenerationStatus(
        id=record.id,
        job_id=record.job_id,
        status=record.status,
        progress=record.progress,
        stage=record.parameters.get("stage", "queued"),
        error=record.error,
        document_id=doc.id if doc else None,
    )


@router.post("", response_model=GenerationStatus, status_code=202)
def create_generation(
    payload: GenerationInput,
    response: Response,
    key: str | None = Header(None, alias="X-Idempotency-Key", max_length=128),
    user: User = Depends(require_roles("school_admin", "teacher")),
    db: Session = Depends(get_db),
):
    payload = payload.model_copy(update={"options": {**payload.options, "execution_mode": "github"}})
    if key is not None and not key.strip():
        raise HTTPException(422, "Idempotency key must not be empty")
    try:
        job_id, generation_id, created = create_record(db, tenant(user), user.id, payload, key)
    except ValueError as error:
        if str(error) == "generation_queue_limit":
            raise HTTPException(429, "School generation queue limit reached") from None
        if str(error) == "school_not_found":
            raise HTTPException(404, "School not found") from None
        raise HTTPException(409, "Idempotency key used for a different request") from None
    except IntegrityError:
        db.rollback()
        # Retrying the same key safely finds the winning committed request.
        job_id, generation_id, created = create_record(db, tenant(user), user.id, payload, key)
    if created:
        enqueue_generation(job_id)
    else:
        response.headers["X-Idempotent-Replay"] = "true"
    return _status(db, generation_id, user)


PRIMARY_SUBJECTS = ["Mathematics", "English", "Integrated Science", "Social Studies", "Religious Education", "Local Language", "Creative Arts and Physical Education"]


def normalize_class(value: str) -> str:
    from services.schemes.schema import grade_name
    return grade_name(value)


def normalize_subject(value: str) -> str:
    from services.schemes.schema import subject_name
    return subject_name(value)


def generation_choices(db, school):
    # Choose the newest curriculum with approved outcomes for each class/subject.
    approved = exists(select(mappings.c.id).where(
        mappings.c.tenant_id == school, mappings.c.topic_id == topics.c.id,
        mappings.c.review_status == "approved"))
    rows = db.execute(select(topics).join(curricula,
        (curricula.c.id == topics.c.curriculum_id) & (curricula.c.tenant_id == school)
    ).where(topics.c.tenant_id == school, approved).order_by(
        curricula.c.created_at.desc(), curricula.c.id.desc(), topics.c.sequence, topics.c.id
    )).mappings().all()
    choices = {}
    for row in rows:
        key = (normalize_class(row["grade"]), normalize_subject(row["subject"]))
        entry = choices.setdefault(key, {"curriculum_id": row["curriculum_id"], "topics": []})
        if entry["curriculum_id"] == row["curriculum_id"]:
            entry["topics"].append(dict(row))
    return choices


@router.get("/options")
def generation_options(user: User = Depends(current_user), db: Session = Depends(get_db)):
    choices = generation_choices(db, tenant(user))
    from services.schemes.service import schedule_options
    grades = [f"P{i}" for i in range(1, 8)]
    grades += sorted({grade for grade, _ in choices} - set(grades))
    result = []
    for grade in grades:
        subjects = list(PRIMARY_SUBJECTS) if re.fullmatch(r"P[1-7]", grade) else []
        subjects += sorted({subject for g, subject in choices if g == grade} - set(subjects))
        result.append({"value": grade, "label": f"Primary {grade[1:]} ({grade})" if re.fullmatch(r"P[1-7]", grade) else grade,
            "subjects": [{"value": subject, "terms": schedule_options(db, tenant(user), grade, subject), "topics": [{"id": str(t["id"]), "title": t["title"]} for t in choices.get((grade, subject), {}).get("topics", [])]} for subject in subjects]})
    return {"classes": result}


class ClassGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: DocumentKind
    grade: str = Field(min_length=1, max_length=80)
    subject: str = Field(min_length=1, max_length=120)
    topic_ids: list[UUID] = Field(default_factory=list, max_length=30)
    term: int | None = Field(default=None, ge=1, le=3)
    week: int | None = Field(default=None, ge=1, le=53)
    lesson: int | None = Field(default=None, ge=1, le=50)
    options: dict = Field(default_factory=dict)
    resource_filters: dict = Field(default_factory=dict)


@router.post("/for-class", response_model=GenerationStatus, status_code=202)
def generate_for_class(payload: ClassGenerationInput, response: Response,
    key: str | None = Header(None, alias="X-Idempotency-Key", max_length=128),
    user: User = Depends(require_roles("school_admin", "teacher")), db: Session = Depends(get_db)):
    options = dict(payload.options)
    if payload.term is not None:
        if payload.week is None:
            raise HTTPException(422, "Select a teaching week.")
        from services.schemes.service import selection
        master, entries = selection(db, tenant(user), payload.grade, payload.subject, payload.term, payload.week, payload.lesson)
        if not master or not entries:
            raise HTTPException(422, "No uploaded scheme covers that term, week and lesson yet.")
        ids = list(dict.fromkeys(UUID(l["topic_id"]) for l in entries))
        if len(ids) > 30:
            raise HTTPException(422, "This week has too many targets for one resource. Select a lesson.")
        if payload.topic_ids and set(payload.topic_ids) != set(ids):
            raise HTTPException(422, "The selected topics do not match the scheme schedule.")
        options["term"] = f"Term {payload.term}"
        options["planning_scope"] = {"class":master["grade"],"subject":master["subject"],"term":payload.term,
            "week":payload.week,"lesson":payload.lesson,"basis":"Uploaded schemes, not official curriculum endorsement",
            "lessons":[{k:l[k] for k in ("lesson","topic","subtopic","objectives","activities","inferred")} for l in entries]}
        import json
        if len(json.dumps(options)) + len(json.dumps(payload.resource_filters)) > 12000:
            raise HTTPException(422, "This selection is too large for one resource. Select a lesson.")
        resolved = GenerationInput(document_type=payload.document_type,curriculum_id=master["curriculum_id"],
            level_id=uuid5(NAMESPACE_URL,f"somaloom-level:{master['curriculum_id']}:{master['grade']}"),
            subject_id=uuid5(NAMESPACE_URL,f"somaloom-subject:{master['curriculum_id']}:{master['subject']}"),
            topic_ids=ids,options=options,resource_filters=payload.resource_filters)
    else:
        entry = generation_choices(db, tenant(user)).get((normalize_class(payload.grade), normalize_subject(payload.subject)))
        if not entry:
            raise HTTPException(422, "No approved topics are available for this class and subject yet.")
        selected = [t for t in entry["topics"] if t["id"] in payload.topic_ids]
        if not selected or {t["id"] for t in selected} != set(payload.topic_ids):
            raise HTTPException(422, "The selected topic is no longer available. Refresh and select a topic again.")
        first = selected[0]
        resolved = GenerationInput(document_type=payload.document_type,
            curriculum_id=entry["curriculum_id"],
            level_id=uuid5(NAMESPACE_URL, f"somaloom-level:{entry['curriculum_id']}:{first['grade']}"),
            subject_id=uuid5(NAMESPACE_URL, f"somaloom-subject:{entry['curriculum_id']}:{first['subject']}"),
            topic_ids=payload.topic_ids, options=options, resource_filters=payload.resource_filters)
    return create_generation(resolved, response, key, user, db)


def work_query(school):
    return select(generations, BackgroundJob.status, BackgroundJob.progress, BackgroundJob.error,
        BackgroundJob.updated_at.label("last_updated_at"), BackgroundJob.finished_at,
        documents.c.id.label("document_id"), documents.c.title.label("document_title")).join(
        BackgroundJob, (BackgroundJob.id == generations.c.job_id) & (BackgroundJob.tenant_id == school)).outerjoin(
        documents, (documents.c.generation_job_id == generations.c.id) & (documents.c.tenant_id == school)).where(generations.c.tenant_id == school)


def work_item(row, user):
    scope = row["parameters"].get("request", {}).get("options", {}).get("planning_scope", {})
    label = [scope.get("class"), normalize_subject(scope["subject"]) if scope.get("subject") else None]
    label += [f"{name.title()} {scope[name]}" for name in ("term", "week", "lesson") if scope.get(name) is not None]
    label.append(row["document_type"].replace("_", " ").capitalize())
    status = row["status"]
    stage = status if status in ("failed", "cancelled", "succeeded") else row["parameters"].get("stage", status)
    events = row["parameters"].get("activity", [])
    if not events:
        events = [{"stage":"queued", "status":"queued", "progress":0, "at":row["created_at"].isoformat()}]
        if status != "queued":
            events.append({"stage":stage, "status":status, "progress":row["progress"], "at":(row["finished_at"] or row["last_updated_at"]).isoformat()})
    if status in ("failed", "cancelled", "succeeded") and events[-1]["status"] != status:
        events = [*events, {"stage":stage, "status":status, "progress":row["progress"], "at":(row["finished_at"] or row["last_updated_at"]).isoformat()}]
    return {"id":str(row["id"]), "job_id":str(row["job_id"]), "title":" · ".join(filter(None,label)),
        "document_type":row["document_type"], "status":status, "stage":stage, "progress":row["progress"], "error":row["error"],
        "created_at":row["created_at"], "updated_at":row["last_updated_at"], "finished_at":row["finished_at"],
        "document_id":str(row["document_id"]) if row["document_id"] else None, "document_title":row["document_title"],
        "scope":{k:v for k,v in scope.items() if k in ("class","subject","term","week","lesson")},
        "topics":[{"topic":l.get("topic", ""), "subtopic":l.get("subtopic", "")} for l in scope.get("lessons",[])],
        "activity":events, "attempts":int(row["parameters"].get("attempts",0)),
        "execution_mode":row["parameters"].get("execution_mode", "ai"),
        "handoff":row["parameters"].get("handoff", {}),
        "last_failure":row["parameters"].get("last_failure"),
        "checkpoint":{"sources_saved":bool(row["parameters"].get("checkpoint",{}).get("evidence_bundle")), "completed_ai_steps":len(row["parameters"].get("checkpoint",{}).get("ai_calls",{}))},
        "can_manage":user.role == "school_admin" or (user.role == "teacher" and row["requested_by"] == user.id)}


@router.get("")
def list_generation_work(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),
    status:str|None=Query(None,pattern="^(queued|running|succeeded|failed|cancelled)$"),
    user:User=Depends(current_user), db:Session=Depends(get_db)):
    from sqlalchemy import func
    query=work_query(tenant(user))
    if user.role == "teacher":query=query.where(generations.c.requested_by == user.id)
    if status:query=query.where(BackgroundJob.status == status)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.execute(query.order_by(generations.c.created_at.desc(),generations.c.id.desc()).offset((page-1)*page_size).limit(page_size)).mappings().all()
    return {"items":[work_item(r,user) for r in rows],"total":total,"page":page,"page_size":page_size}


@router.get("/{generation_id}/activity")
def generation_activity(generation_id:UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.execute(work_query(tenant(user)).where(generations.c.id == generation_id)).mappings().first()
    if not row:raise HTTPException(404,"Generation not found")
    return work_item(row,user)


@router.get("/{generation_id}", response_model=GenerationStatus)
def get_generation(
    generation_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return _status(db, generation_id, user)


@router.post("/{generation_id}/cancel", response_model=GenerationStatus)
def cancel_generation(
    generation_id: UUID,
    user: User = Depends(require_roles("school_admin", "teacher")),
    db: Session = Depends(get_db),
):
    record = owned_record(db, generation_id, tenant(user))
    if not record or (user.role == "teacher" and record.requested_by != user.id):
        raise HTTPException(404, "Generation not found")
    job = db.get(BackgroundJob, record.job_id, with_for_update=True)
    if job.status in ("succeeded", "failed"):
        raise HTTPException(409, "Generation already finished")
    if job.status != "cancelled":
        from datetime import datetime, timezone

        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        from services.generation.repository import activity_event
        params = activity_event(record.parameters, "cancelled", job.progress, "cancelled")
        db.execute(
            generations.update()
            .where(generations.c.id == generation_id, generations.c.tenant_id == tenant(user))
            .values(parameters=params)
        )
        db.commit()
    return _status(db, generation_id, user)


@router.post("/{generation_id}/handoff",response_model=GenerationStatus,status_code=202)
def handoff_generation(generation_id:UUID,user:User=Depends(require_roles("school_admin","teacher")),db:Session=Depends(get_db)):
    record=owned_record(db,generation_id,tenant(user))
    if not record or (user.role=="teacher" and record.requested_by!=user.id):raise HTTPException(404,"Generation not found")
    job=db.get(BackgroundJob,record.job_id,with_for_update=True)
    if job.status in ("running","succeeded"):raise HTTPException(409,"Wait for the active request to finish before changing its delivery")
    from services.generation.repository import activity_event
    params=dict(record.parameters)
    if job.error:params['last_failure']={'code':job.error,'at':(job.finished_at or job.updated_at).isoformat()}
    params['execution_mode']='github'
    stage='awaiting_external' if params.get('handoff',{}).get('issue_url') else 'preparing_github'
    params=activity_event(params,stage,job.progress,'queued')
    job.status='queued';job.error=None;job.finished_at=None
    db.execute(generations.update().where(generations.c.id==generation_id,generations.c.tenant_id==tenant(user)).values(parameters=params));db.commit()
    return _status(db,generation_id,user)


@router.post("/{generation_id}/retry", response_model=GenerationStatus, status_code=202)
def retry_generation(
    generation_id: UUID,
    user: User = Depends(require_roles("school_admin", "teacher")),
    db: Session = Depends(get_db),
):
    record = owned_record(db, generation_id, tenant(user))
    if not record or (user.role == "teacher" and record.requested_by != user.id):
        raise HTTPException(404, "Generation not found")
    job = db.get(BackgroundJob, record.job_id, with_for_update=True)
    if job.status != "failed":
        raise HTTPException(409, "Only failed generations can be retried")
    params = dict(record.parameters)
    attempts = int(params.get("attempts", 0))
    params["execution_mode"]="github"
    if params.get("execution_mode")=="github":
        from services.generation.repository import activity_event
        job.status='queued';job.error=None;job.finished_at=None
        stage='awaiting_external' if params.get('handoff',{}).get('issue_url') else 'preparing_github'
        params=activity_event(params,stage,job.progress,'queued')
        db.execute(generations.update().where(generations.c.id==generation_id,generations.c.tenant_id==tenant(user)).values(parameters=params));db.commit()
        return _status(db,generation_id,user)
    if attempts >= 2:
        raise HTTPException(409, "Retry limit reached")
    # RQ job IDs from prior failures can linger; remove finished job before redelivery.
    from rq.exceptions import NoSuchJobError
    from rq.job import Job

    from app.core.queue import redis_connection

    try:
        previous = Job.fetch("generation-" + str(job.id), connection=redis_connection())
        if previous.is_started or previous.is_queued:
            raise HTTPException(409, "Worker still owns generation")
        previous.delete()
    except NoSuchJobError:
        pass
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Generation queue unavailable") from None
    job.status, job.error, job.finished_at = "queued", None, None
    from services.generation.repository import activity_event
    params = activity_event(params, "retry_queued", job.progress, "queued")
    params["attempts"] = attempts + 1
    db.execute(
        generations.update()
        .where(generations.c.id == generation_id, generations.c.tenant_id == tenant(user))
        .values(parameters=params)
    )
    db.commit()
    enqueue_generation(job.id)
    return _status(db, generation_id, user)


@router.get("/{generation_id}/draft")
def get_draft(
    generation_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not owned_record(db, generation_id, tenant(user)):
        raise HTTPException(404, "Generation not found")
    draft = draft_record(db, generation_id, tenant(user))
    if not draft:
        raise HTTPException(404, "Draft not yet available")
    from sqlalchemy import select

    from app.core.models import documents, versions

    row = (
        db.execute(
            select(versions.c.id, documents.c.title, documents.c.document_type)
            .join(documents, documents.c.id == versions.c.document_id)
            .where(
                documents.c.id == draft.id,
                versions.c.version == draft.version,
                versions.c.tenant_id == tenant(user),
            )
        )
        .mappings()
        .one()
    )
    return {
        "document_id": str(draft.id),
        "version": draft.version,
        "document": {
            "id": str(row["id"]),
            "title": row["title"],
            "document_type": row["document_type"],
            "review_state": "draft",
            "evidence_ids": draft.body.get("evidence_ids", []),
            "body": draft.body,
        },
    }

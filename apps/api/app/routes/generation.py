"""Authenticated tenant-isolated generation endpoints; no prompt code execution."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import current_user, require_roles
from app.core.config import get_settings
from app.core.database import get_db
from app.core.models import BackgroundJob, User, generations
from services.ai.provider import provider_available
from services.generation.repository import (
    create_record, draft_record, owned_record,
)
from services.generation.schema import GenerationInput, GenerationStatus
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
        id=record.id, job_id=record.job_id, status=record.status,
        progress=record.progress, stage=record.parameters.get("stage", "queued"),
        error=record.error, document_id=doc.id if doc else None,
    )


@router.post("", response_model=GenerationStatus, status_code=202)
def create_generation(
    payload: GenerationInput, response: Response,
    key: str | None = Header(None, alias="X-Idempotency-Key", max_length=128),
    user: User = Depends(require_roles("school_admin", "teacher")),
    db: Session = Depends(get_db),
):
    if not provider_available(get_settings().ai_provider):
        raise HTTPException(503, "AI generation provider not configured")
    if key is not None and not key.strip():
        raise HTTPException(422, "Idempotency key must not be empty")
    try:
        job_id, generation_id, created = create_record(db, tenant(user), user.id, payload, key)
    except ValueError:
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


@router.get("/{generation_id}", response_model=GenerationStatus)
def get_generation(
    generation_id: UUID,
    user: User = Depends(current_user), db: Session = Depends(get_db),
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
        params = dict(record.parameters)
        params["stage"] = "cancelled"
        db.execute(generations.update().where(
            generations.c.id == generation_id,
            generations.c.tenant_id == tenant(user)).values(parameters=params))
        db.commit()
    return _status(db, generation_id, user)


@router.post("/{generation_id}/retry", response_model=GenerationStatus, status_code=202)
def retry_generation(
    generation_id: UUID,
    user: User = Depends(require_roles("school_admin", "teacher")),
    db: Session = Depends(get_db),
):
    record = owned_record(db, generation_id, tenant(user))
    if not record:
        raise HTTPException(404, "Generation not found")
    job = db.get(BackgroundJob, record.job_id, with_for_update=True)
    if job.status != "failed":
        raise HTTPException(409, "Only failed generations can be retried")
    params = dict(record.parameters)
    attempts = int(params.get("attempts", 0))
    if attempts >= 2:
        raise HTTPException(409, "Retry limit reached")
    # RQ job IDs from prior failures can linger; remove finished job before redelivery.
    from app.core.queue import redis_connection
    try:
        from rq.job import Job
        previous = Job.fetch("generation-" + str(job.id), connection=redis_connection())
        if previous.is_started or previous.is_queued:
            raise HTTPException(409, "Worker still owns generation")
        previous.delete()
    except HTTPException:
        raise
    except Exception:
        pass
    job.status, job.progress, job.error, job.finished_at = "queued", 0, None, None
    params.update(stage="queued", attempts=attempts + 1)
    db.execute(generations.update().where(
        generations.c.id == generation_id,
        generations.c.tenant_id == tenant(user)).values(parameters=params))
    db.commit()
    enqueue_generation(job.id)
    return _status(db, generation_id, user)


@router.get("/{generation_id}/draft")
def get_draft(
    generation_id: UUID,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    if not owned_record(db, generation_id, tenant(user)):
        raise HTTPException(404, "Generation not found")
    draft = draft_record(db, generation_id, tenant(user))
    if not draft:
        raise HTTPException(404, "Draft not yet available")
    return {"document_id": draft.id, "version": draft.version, "document": draft.body}

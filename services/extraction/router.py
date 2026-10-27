"""Tenant-authenticated extraction API; register router from the API composition owner."""

from __future__ import annotations

from uuid import UUID

from app.auth.security import require_roles
from app.core.database import get_db
from app.core.models import BackgroundJob, User, extractions
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.extraction.jobs import (
    create_extraction,
    dispatch,
    load_document,
)

router = APIRouter(prefix="/extractions", tags=["extractions"])


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_version_id: UUID


def _tenant(user: User) -> UUID:
    # Platform-admin cross-school access needs an explicitly scoped delegation flow.
    if user.tenant_id is None:
        raise HTTPException(403, "School scope required")
    return user.tenant_id


def _status(db: Session, tenant_id: UUID, extraction_id: UUID):
    row = (
        db.execute(
            select(
                extractions.c.id,
                extractions.c.resource_version_id,
                BackgroundJob.status,
                BackgroundJob.progress,
                BackgroundJob.error,
            )
            .join(BackgroundJob, BackgroundJob.id == extractions.c.job_id)
            .where(
                extractions.c.id == extraction_id,
                extractions.c.tenant_id == tenant_id,
                BackgroundJob.tenant_id == tenant_id,
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404, "Extraction unavailable")
    return dict(row)


@router.post("", status_code=202)
def submit_extraction(
    payload: ExtractionRequest,
    user: User = Depends(require_roles("school_admin", "teacher")),
    db: Session = Depends(get_db),
):
    tenant = _tenant(user)
    try:
        eid, jid, _ = create_extraction(db, tenant, payload.resource_version_id)
    except LookupError:
        raise HTTPException(404, "Resource version unavailable") from None
    try:
        dispatch(jid)
    except Exception:
        # Job remains queued in SQL for the reconciliation service; no false success claim.
        raise HTTPException(
            503, "Job persisted, but queue unavailable; retry or reconcile"
        ) from None
    return {"extraction_id": eid, "job_id": jid, "status": "queued_or_existing"}


@router.get("/{extraction_id}")
def get_extraction(
    extraction_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("school_admin", "teacher", "reviewer")),
):
    return _status(db, _tenant(user), extraction_id)


@router.get("/{extraction_id}/document")
def get_extracted_document(
    extraction_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("school_admin", "teacher", "reviewer")),
):
    _status(db, _tenant(user), extraction_id)
    doc = load_document(db, _tenant(user), extraction_id)
    if doc is None:
        raise HTTPException(409, "Extraction output is not available yet")
    return doc

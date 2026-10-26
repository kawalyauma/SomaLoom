"""Tenant-safe publishing adapter for Agent 1's existing FastAPI application.

Agent 1 must include this router after reviewing the interface. No central
authentication, migrations or schema ownership is changed by Agent 8.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, insert, select
from sqlalchemy.orm import Session

from app.auth.router import audit
from app.auth.security import current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.models import (
    BackgroundJob,
    User,
    documents,
    exports,
    reviews,
    versions,
    utcnow,
)
from app.core.storage import LocalObjectStore
from services.export.publishing import export_docx, export_pdf
from services.rendering.document import DocumentValidationError

router = APIRouter(tags=["publishing"])


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_version_id: UUID
    format: Literal["pdf", "docx"]
    audience: Literal["student", "teacher"] = "student"


def _school_user(user: User) -> UUID:
    """Platform admins must explicitly assume an audited school context first."""
    if not user.tenant_id or user.role not in {"school_admin", "teacher", "reviewer"}:
        raise HTTPException(403, "A school membership is required")
    return user.tenant_id


def _version(db: Session, version_id: UUID, tenant_id: UUID):
    row = db.execute(
        select(
            versions.c.id,
            versions.c.body,
            documents.c.title,
            documents.c.document_type,
        )
        .join(
            documents,
            and_(
                documents.c.id == versions.c.document_id,
                documents.c.tenant_id == versions.c.tenant_id,
            ),
        )
        .where(versions.c.id == version_id, versions.c.tenant_id == tenant_id)
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Document version not found")
    return row


def _latest_decision(db: Session, version_id: UUID, tenant_id: UUID) -> str | None:
    return db.scalar(
        select(reviews.c.decision)
        .where(reviews.c.document_version_id == version_id, reviews.c.tenant_id == tenant_id)
        .order_by(reviews.c.created_at.desc())
        .limit(1)
    )


@router.get("/documents")
def list_documents(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    tenant = _school_user(user)
    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(422, "Invalid pagination")
    scope = documents.c.tenant_id == tenant
    total = db.scalar(select(func.count()).select_from(documents).where(scope)) or 0
    rows = db.execute(
        select(documents.c.id, documents.c.title, documents.c.document_type)
        .where(scope).order_by(documents.c.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).mappings().all()
    return {"items": [dict(row) for row in rows], "page": page, "page_size": page_size, "total": total}


@router.post("/exports", status_code=201)
def publish(
    payload: ExportRequest,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    tenant = _school_user(user)
    if payload.audience == "teacher" and user.role not in {"teacher", "school_admin", "reviewer"}:
        raise HTTPException(403, "Teacher-only publication forbidden")
    record = _version(db, payload.document_version_id, tenant)
    if _latest_decision(db, payload.document_version_id, tenant) != "approved":
        raise HTTPException(409, "Educator approval required for this document version")
    body = record["body"]
    if not isinstance(body, dict):
        raise HTTPException(422, "Document body is invalid")
    # An explicit document version is immutable; each export is a new object key.
    doc = {
        "title": record["title"],
        "document_type": record["document_type"],
        "review_state": "approved",
        "body": body,
        "evidence_ids": body.get("evidence_ids", []),
    }
    try:
        renderer = export_pdf if payload.format == "pdf" else export_docx
        content = renderer(doc, audience=payload.audience)
    except (DocumentValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except ModuleNotFoundError as exc:
        raise HTTPException(503, "Publishing dependencies unavailable") from exc
    if len(content) > 30 * 1024 * 1024:
        raise HTTPException(413, "Export exceeds maximum permitted size")
    export_id, job_id = uuid4(), uuid4()
    object_key = (
        "published/" + str(payload.document_version_id) + "/" + payload.audience
        + "/" + str(export_id) + "." + payload.format
    )
    # Storage is tenant-partitioned; the DB reference is created only after write.
    store = LocalObjectStore(get_settings().storage_root)
    store.put(tenant, object_key, content)
    job = BackgroundJob(
        id=job_id, tenant_id=tenant, kind="export",
        status="succeeded", progress=100, finished_at=utcnow(),
    )
    db.add(job)
    db.flush()
    db.execute(insert(exports).values(
        id=export_id, tenant_id=tenant, document_version_id=payload.document_version_id,
        job_id=job_id, format=payload.format, object_key=object_key,
    ))
    audit(db, user, "export.create", export_id, request)
    db.commit()
    return {
        "id": str(export_id),
        "job_id": str(job_id),
        "format": payload.format,
        "status": "succeeded",
        "download_url": "/api/v1/exports/" + str(export_id) + "/download",
    }


@router.get("/exports/{export_id}/download")
def download(
    export_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    tenant = _school_user(user)
    row = db.execute(
        select(exports.c.object_key, exports.c.format)
        .where(exports.c.id == export_id, exports.c.tenant_id == tenant)
    ).mappings().first()
    if not row or not row["object_key"]:
        raise HTTPException(404, "Export not found")
    if "/teacher/" in row["object_key"] and user.role not in {"teacher", "school_admin", "reviewer"}:
        raise HTTPException(403, "Teacher-only publication forbidden")
    try:
        content = LocalObjectStore(get_settings().storage_root).get(tenant, row["object_key"])
    except FileNotFoundError:
        raise HTTPException(404, "Export file no longer available") from None
    media_type = (
        "application/pdf"
        if row["format"] == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    response = Response(content=content, media_type=media_type)
    response.headers["Content-Disposition"] = (
        'attachment; filename="somaloom-' + str(export_id) + '.' + row["format"] + '"'
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

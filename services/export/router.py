"""Tenant-safe publishing adapter for Agent 1's existing FastAPI application.

Agent 1 must include this router after reviewing the interface. No central
authentication, migrations or schema ownership is changed by Agent 8.
"""
from __future__ import annotations

from typing import Any, Literal
import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, insert, select
from sqlalchemy.orm import Session

from app.auth.router import audit
from app.auth.security import current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.models import (
    BackgroundJob,
    School,
    User,
    evidence,
    documents,
    exports,
    reviews,
    versions,
    utcnow,
)
from app.core.storage import LocalObjectStore
from services.export.publishing import export_docx, export_pdf
from services.rendering.document import DocumentValidationError, validate_document
from services.rendering.omml import latex_to_omml

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


def _validate_evidence(db: Session, tenant: UUID, body: dict[str, Any]) -> None:
    """Prevent invented/cross-school evidence IDs from reaching approved exports."""
    source_ids = body.get("evidence_ids", [])
    if not isinstance(source_ids, list):
        raise HTTPException(422, "Document evidence must be a list")
    try:
        ids = [UUID(str(value)) for value in source_ids]
    except (ValueError, TypeError):
        raise HTTPException(422, "Evidence identifiers must be UUIDs") from None
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Duplicate evidence references")
    if not ids:
        return
    actual = db.execute(
        select(evidence.c.id, evidence.c.provenance)
        .where(evidence.c.id.in_(ids), evidence.c.tenant_id == tenant)
    ).mappings().all()
    if len(actual) != len(ids):
        raise HTTPException(422, "Evidence references are not all accessible in this school")
    for item in actual:
        provenance = item["provenance"]
        if not isinstance(provenance, dict) or not provenance.get("source_uri") or not provenance.get("license"):
            raise HTTPException(422, "Source attribution or license is missing")


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
        select(documents.c.id, documents.c.title, documents.c.document_type, documents.c.generation_job_id)
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
    _validate_evidence(db, tenant, body)
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
        school = db.get(School, tenant)
        content = renderer(doc, branding={"school_name": school.name if school else "SomaLoom"}, audience=payload.audience)
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


class DocumentVersionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    body: dict[str, Any]


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    comments: str = Field(min_length=8, max_length=4000)
    # Reviewers explicitly attest that these checks were performed.
    citations_checked: bool = False
    mathematics_checked: bool = False
    licensing_checked: bool = False


def _document(db: Session, document_id: UUID, tenant: UUID):
    row = db.execute(
        select(documents.c.id, documents.c.title, documents.c.document_type)
        .where(documents.c.id == document_id, documents.c.tenant_id == tenant)
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Document not found")
    return row


@router.get("/documents/{document_id}/versions")
def list_versions(
    document_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    tenant = _school_user(user)
    _document(db, document_id, tenant)
    rows = db.execute(
        select(versions.c.id, versions.c.version, versions.c.created_at)
        .where(versions.c.document_id == document_id, versions.c.tenant_id == tenant)
        .order_by(versions.c.version.desc()).limit(100)
    ).mappings().all()
    return {"items": [dict(r) for r in rows], "page": 1, "page_size": 100, "total": len(rows)}


@router.get("/documents/{document_id}/versions/{version_id}")
def get_version(
    document_id: UUID,
    version_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    tenant = _school_user(user)
    document = _document(db, document_id, tenant)
    row = db.execute(
        select(versions.c.id, versions.c.version, versions.c.body)
        .where(versions.c.id == version_id,
               versions.c.document_id == document_id,
               versions.c.tenant_id == tenant)
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Document version not found")
    return {
        "id": str(row["id"]), "document_id": str(document_id),
        "version": row["version"], "title": document["title"],
        "document_type": document["document_type"],
        "body": row["body"],
        "evidence_ids": row["body"].get("evidence_ids", []),
        "review_state": _latest_decision(db, version_id, tenant) or "draft",
    }


@router.post("/documents/{document_id}/versions", status_code=201)
def save_version(
    document_id: UUID,
    payload: DocumentVersionEdit,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    tenant = _school_user(user)
    if user.role not in {"school_admin", "teacher"}:
        raise HTTPException(403, "Only teachers and school administrators can edit")
    document = _document(db, document_id, tenant)
    # Bound the size of mutable JSON to prevent pathological render work.
    if len(json.dumps(payload.body)) > 2_000_000:
        raise HTTPException(413, "Document revision too large")
    try:
        validate_document({
            "title": document["title"],
            "body": payload.body,
            "evidence_ids": payload.body.get("evidence_ids", []),
        }, audience="teacher", strict_visuals=False)
    except DocumentValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    current = db.execute(
        select(versions.c.id, versions.c.version)
        .where(versions.c.document_id == document_id, versions.c.tenant_id == tenant)
        .order_by(versions.c.version.desc()).limit(1).with_for_update()
    ).mappings().first()
    if not current or current["version"] != payload.expected_version:
        raise HTTPException(409, "Revision conflict; reload the newest version")
    next_id = uuid4()
    db.execute(insert(versions).values(
        id=next_id, tenant_id=tenant, document_id=document_id,
        version=current["version"] + 1, body=payload.body
    ))
    audit(db, user, "document.version.create", next_id, request)
    db.commit()
    return {"id": str(next_id), "document_id": str(document_id),
            "version": current["version"] + 1, "review_state": "draft"}


@router.post("/documents/{document_id}/versions/{version_id}/review", status_code=201)
def review_version(
    document_id: UUID,
    version_id: UUID,
    payload: ReviewDecision,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    tenant = _school_user(user)
    if user.role not in {"school_admin", "reviewer"}:
        raise HTTPException(403, "Reviewer permission required")
    document = _document(db, document_id, tenant)
    record = db.execute(
        select(versions.c.body)
        .where(versions.c.id == version_id, versions.c.document_id == document_id,
               versions.c.tenant_id == tenant)
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, "Document version not found")
    if payload.decision == "approved":
        _validate_evidence(db, tenant, record)
        if not (payload.citations_checked and payload.mathematics_checked and payload.licensing_checked):
            raise HTTPException(422, "All educator verification attestations are required")
        try:
            data = validate_document({
                "title": document["title"], "body": record,
                "evidence_ids": record.get("evidence_ids", []),
            }, audience="teacher")
            for section in data["body"]["sections"]:
                for block in section["blocks"]:
                    if block["type"] == "equation":
                        latex_to_omml(block["latex"])
        except (DocumentValidationError, ValueError) as exc:
            raise HTTPException(422, "Document failed publication preflight: " + str(exc)) from exc
    decision_id = uuid4()
    db.execute(insert(reviews).values(
        id=decision_id, tenant_id=tenant, document_version_id=version_id,
        reviewer_id=user.id, decision=payload.decision, comments=payload.comments
    ))
    audit(db, user, "document.review." + payload.decision, decision_id, request)
    db.commit()
    return {"id": str(decision_id), "document_version_id": str(version_id),
            "decision": payload.decision}

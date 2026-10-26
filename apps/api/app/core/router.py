import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.router import audit
from app.auth.security import current_user, require_roles
from app.core.config import get_settings
from app.core.database import get_db
from app.core.models import BackgroundJob, Organization, School, User
from app.core.queue import redis_connection
from app.core.schemas import (
    Configuration,
    Health,
    JobOut,
    OrganizationCreate,
    OrganizationOut,
    Readiness,
    SchoolCreate,
    SchoolOut,
)
from contracts.v1.schemas import (
    ContentBlock,
    CurriculumOutcome,
    Equation,
    EvidenceLink,
    Export,
    Extraction,
    GeneratedDocument,
    GenerationJob,
    Page,
    Resource,
    ResourceVersion,
    VisualAsset,
)

router = APIRouter()


@router.get("/health", response_model=Health, tags=["system"])
def health():
    return Health(status="ok")


@router.get("/ready", response_model=Readiness, tags=["system"])
def ready(response: Response, db: Session = Depends(get_db)):
    database = redis = worker = False
    try:
        db.execute(text("SELECT 1"))
        database = True
    except Exception:
        pass
    try:
        connection = redis_connection()
        redis = bool(connection.ping())
        worker = bool(connection.exists("somaloom:worker:heartbeat"))
    except Exception:
        pass
    good = database and redis and worker
    response.status_code = 200 if good else 503
    return Readiness(
        status="ready" if good else "unavailable", database=database, redis=redis, worker=worker
    )


@router.get("/config", response_model=Configuration, tags=["system"])
def config(user: User = Depends(current_user)):
    return Configuration(
        api_version="v1",
        runtime_ai_configured=get_settings().ai_provider != "disabled",
        document_types=[
            "notes",
            "exam",
            "test",
            "scheme",
            "lesson_plan",
            "teacher_guide",
            "marking_guide",
            "worksheet",
        ],
    )


@router.post("/organizations", response_model=OrganizationOut, status_code=201, tags=["tenancy"])
def create_organization(
    data: OrganizationCreate,
    request: Request,
    user: User = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    org = Organization(name=data.name)
    db.add(org)
    db.flush()
    audit(db, user, "organization.create", org.id, request)
    db.commit()
    return org


@router.get("/organizations", response_model=Page[OrganizationOut], tags=["tenancy"])
def organizations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = select(Organization)
    if user.role != "platform_admin":
        school = db.get(School, user.tenant_id)
        query = query.where(Organization.id == school.organization_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    return dict(
        items=db.scalars(
            query.order_by(Organization.id).offset((page - 1) * page_size).limit(page_size)
        ).all(),
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/schools", response_model=SchoolOut, status_code=201, tags=["tenancy"])
def create_school(
    data: SchoolCreate,
    request: Request,
    user: User = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    if not db.get(Organization, data.organization_id):
        raise HTTPException(404, "Organization not found")
    school = School(**data.model_dump())
    db.add(school)
    db.flush()
    audit(db, user, "school.create", school.id, request)
    db.commit()
    return school


@router.get("/schools", response_model=Page[SchoolOut], tags=["tenancy"])
def schools(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = select(School)
    if user.role != "platform_admin":
        query = query.where(School.id == user.tenant_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    return dict(
        items=db.scalars(
            query.order_by(School.id).offset((page - 1) * page_size).limit(page_size)
        ).all(),
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/schools/{school_id}", response_model=SchoolOut, tags=["tenancy"])
def school(school_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "platform_admin" and school_id != user.tenant_id:
        raise HTTPException(404, "School not found")
    record = db.get(School, school_id)
    if not record:
        raise HTTPException(404, "School not found")
    return record


@router.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"])
def job(job_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(BackgroundJob).where(BackgroundJob.id == job_id)
    if user.role != "platform_admin":
        query = query.where(BackgroundJob.tenant_id == user.tenant_id)
    record = db.scalar(query)
    if not record:
        raise HTTPException(404, "Job not found")
    return record


MockPayload = (
    Resource
    | ResourceVersion
    | Extraction
    | ContentBlock
    | VisualAsset
    | Equation
    | CurriculumOutcome
    | EvidenceLink
    | GenerationJob
    | GeneratedDocument
    | Export
)
MockKind = Literal[
    "resource",
    "resource_version",
    "extraction",
    "content_block",
    "visual_asset",
    "equation",
    "curriculum_outcome",
    "evidence_link",
    "generation_job",
    "generated_document",
    "export",
]


@router.get("/mocks/{contract}", response_model=MockPayload, tags=["development mocks"])
def mock_resource(contract: MockKind, user: User = Depends(current_user)):
    if get_settings().app_env != "development":
        raise HTTPException(404, "Not found")
    payload = json.loads(
        (Path(__file__).resolve().parents[4] / f"contracts/v1/fixtures/{contract}.json").read_text()
    )
    if user.tenant_id:
        payload["tenant_id"] = str(user.tenant_id)
    return payload

"""Feature router; register with app.include_router(router, prefix='/api/v1')."""
import hmac
import ipaddress
import os
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import current_user, require_roles
from app.core.database import get_db
from app.core.models import AuditLog, BackgroundJob, User, resources, resource_versions, sources
from services.ingestion.crawler import allowed, canonical
from services.ingestion.jobs import enqueue
from services.ingestion.library import (
    MAX_FILES, get_resource, list_resources, object_store, publish_version, read_upload,
)
from services.ingestion.models import import_runs, telegram_receipts

router = APIRouter(tags=["resource ingestion"])

def school_id(user: User) -> UUID:
    if not user.tenant_id:
        raise HTTPException(403, "Explicit school membership required")
    return user.tenant_id

def audit(db, user, action, target):
    db.add(AuditLog(tenant_id=school_id(user), actor_id=user.id,
                    action=action, target_id=str(target)))

class MetadataPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    license: str | None = Field(None, min_length=1, max_length=300)

class SourceCreate(BaseModel):
    kind: Literal["web", "telegram"]
    source_uri: str | None = Field(None, min_length=1, max_length=1000)
    license: str = Field(min_length=1, max_length=300)
    domains: list[str] = Field(default_factory=list, max_length=20)
    paths: list[str] = Field(default_factory=lambda: ["/"], max_length=20)
    chat_id: str | None = Field(None, max_length=80)

class WebStart(BaseModel):
    source_id: UUID
    url: str = Field(max_length=2000)
    max_pages: int = Field(default=100, ge=1, le=1000)
    max_depth: int = Field(default=2, ge=0, le=8)
    delay: float = Field(default=1, ge=0.5, le=60)
    dry_run: bool = False

class TelegramStart(BaseModel):
    source_id: UUID

@router.post("/resources/uploads", status_code=201)
async def upload(
    files: list[UploadFile] = File(...), license: str = Form(...),
    title: str | None = Form(None), source_uri: str | None = Form(None),
    source_id: UUID | None = Form(None),
    resource_id: UUID | None = Form(None),
    user: User = Depends(require_roles("school_admin", "teacher")),
    db: Session = Depends(get_db),
):
    tenant = school_id(user)
    if not files or len(files) > MAX_FILES:
        raise HTTPException(422, "Invalid number of files")
    if source_id:
        owner = db.execute(select(sources).where(
            sources.c.id == source_id, sources.c.tenant_id == tenant,
            sources.c.kind == "web"
        )).mappings().first()
        if not owner or not owner["config"].get("active", False):
            raise HTTPException(404, "Source not found")
        if not source_uri or not allowed(source_uri, set(owner["config"]["domains"]),
                                          owner["config"].get("paths", ["/"])):
            raise HTTPException(422, "Import URL outside source policy")
    if resource_id and len(files) != 1:
        raise HTTPException(422, "New version requires a single file")
    if resource_id:
        get_resource(db, tenant, resource_id)
    outcomes = []
    for file in files:
        data, mime, name, digest = await read_upload(file)
        result = publish_version(
            db, tenant, user.id, data, mime, name, digest,
            title or name, license, source_uri or f"upload://{tenant}/{digest}",
            "web" if source_id else "upload", source_id, resource_id,
        )
        outcomes.append(result)
    return {"items": outcomes}

@router.get("/resources")
def resources_list(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200), mime: str | None = None,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    return list_resources(db, school_id(user), q, mime, page, page_size)

@router.get("/resources/{resource_id}")
def resource_detail(resource_id: UUID, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    tenant = school_id(user)
    record = get_resource(db, tenant, resource_id)
    versions = db.execute(select(resource_versions).where(
        resource_versions.c.tenant_id == tenant,
        resource_versions.c.resource_id == resource_id,
    ).order_by(resource_versions.c.version.desc())).mappings().all()
    return {"resource": record, "versions": [dict(v) for v in versions]}

@router.get("/resources/{resource_id}/download")
def download_resource(resource_id: UUID, version: int | None = Query(None, ge=1),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    tenant = school_id(user)
    resource = get_resource(db, tenant, resource_id)
    query = select(resource_versions).where(
        resource_versions.c.tenant_id == tenant,
        resource_versions.c.resource_id == resource_id,
    )
    if version:
        query = query.where(resource_versions.c.version == version)
    record = db.execute(query.order_by(resource_versions.c.version.desc()).limit(1)).mappings().first()
    if not record:
        raise HTTPException(404, "Version not found")
    return Response(content=object_store().get(tenant, record["object_key"]),
                    media_type=resource["media_type"], headers={"Cache-Control": "private, no-store"})

@router.patch("/resources/{resource_id}")
def edit_metadata(resource_id: UUID, data: MetadataPatch,
                  user: User = Depends(require_roles("school_admin")),
                  db: Session = Depends(get_db)):
    tenant = school_id(user)
    record = get_resource(db, tenant, resource_id)
    provenance = dict(record["provenance"])
    if data.license is not None:
        provenance["license_override"] = data.license
    if data.title is None and data.license is None:
        raise HTTPException(422, "No changes supplied")
    db.execute(resources.update().where(
        resources.c.id == resource_id, resources.c.tenant_id == tenant
    ).values(title=data.title or record["title"], provenance=provenance))
    audit(db, user, "ingestion.resource.metadata_updated", resource_id)
    db.commit()
    return get_resource(db, tenant, resource_id)

@router.delete("/resources/{resource_id}", status_code=204)
def delete_resource(resource_id: UUID, user: User = Depends(require_roles("school_admin")),
                    db: Session = Depends(get_db)):
    tenant = school_id(user)
    record = get_resource(db, tenant, resource_id)
    provenance = dict(record["provenance"])
    provenance["deleted_at"] = datetime.now(timezone.utc).isoformat()
    db.execute(resources.update().where(
        resources.c.id == resource_id, resources.c.tenant_id == tenant
    ).values(provenance=provenance))
    audit(db, user, "ingestion.resource.deleted", resource_id)
    db.commit()
    return Response(status_code=204)

@router.post("/sources", status_code=201)
def create_source(data: SourceCreate, user: User = Depends(require_roles("school_admin")),
                  db: Session = Depends(get_db)):
    tenant = school_id(user)
    if data.kind == "web":
        if not data.source_uri:
            raise HTTPException(422, "Web source URL required")
        if not data.domains or any(not d or "://" in d or "/" in d or ":" in d for d in data.domains):
            raise HTTPException(422, "Explicit DNS domain allowlist required")
        domains = [d.lower().rstrip(".") for d in data.domains]
        for domain in domains:
            try:
                ip = ipaddress.ip_address(domain)
            except ValueError:
                if domain in {"localhost", "localhost.localdomain"} or domain.endswith(".local"):
                    raise HTTPException(422, "Local or private hosts are prohibited") from None
            else:
                if not ip.is_global:
                    raise HTTPException(422, "Local or private hosts are prohibited")
        if not all(p.startswith("/") and ".." not in p for p in data.paths):
            raise HTTPException(422, "Invalid allowed paths")
        if not allowed(data.source_uri, set(domains), data.paths):
            raise HTTPException(422, "Source URL outside authorized scope")
        config = {"active": True, "domains": domains, "paths": data.paths}
        url = canonical(data.source_uri)
    else:
        if not data.chat_id or not data.chat_id.lstrip("-").isdigit():
            raise HTTPException(422, "Numeric Telegram chat ID required")
        if not os.getenv("SOMALOOM_TELEGRAM_BOT_TOKEN"):
            raise HTTPException(503, "Telegram integration not configured")
        existing = db.execute(select(sources).where(sources.c.kind == "telegram")).mappings().all()
        if any(r["config"].get("active", True) and r["config"].get("chat_id") == data.chat_id for r in existing):
            raise HTTPException(409, "Chat already linked to an existing school")
        config = {"active": True, "chat_id": data.chat_id}
        url = f"telegram://{data.chat_id}"
    source_id = uuid4()
    db.execute(sources.insert().values(
        id=source_id, tenant_id=tenant, kind=data.kind,
        source_uri=url, license=data.license, config=config,
    ))
    audit(db, user, "ingestion.source.connected", source_id)
    db.commit()
    return {"id": source_id, "kind": data.kind, "source_uri": url, "config": config}

@router.get("/sources")
def list_sources(user: User = Depends(current_user), db: Session = Depends(get_db),
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    tenant = school_id(user)
    query = select(sources).where(sources.c.tenant_id == tenant)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(sources.c.created_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).mappings().all()
    return {"items": [dict(x) for x in rows], "page": page, "page_size": page_size, "total": total}

@router.post("/sources/{source_id}/disconnect")
def disconnect_source(source_id: UUID, user: User = Depends(require_roles("school_admin")),
                      db: Session = Depends(get_db)):
    tenant = school_id(user)
    src = db.execute(select(sources).where(
        sources.c.id == source_id, sources.c.tenant_id == tenant)).mappings().first()
    if not src:
        raise HTTPException(404, "Source not found")
    config = dict(src["config"])
    config["active"] = False
    db.execute(sources.update().where(
        sources.c.id == source_id, sources.c.tenant_id == tenant).values(config=config))
    audit(db, user, "ingestion.source.disconnected", source_id)
    db.commit()
    return {"id": source_id, "active": False}

@router.post("/imports/web", status_code=202)
def start_web(data: WebStart, user: User = Depends(require_roles("school_admin")),
              db: Session = Depends(get_db)):
    tenant = school_id(user)
    source = db.execute(select(sources).where(
        sources.c.tenant_id == tenant, sources.c.id == data.source_id,
        sources.c.kind == "web")).mappings().first()
    if not source or not source["config"].get("active", False):
        raise HTTPException(404, "Source unavailable")
    if not allowed(data.url, set(source["config"]["domains"]), source["config"].get("paths", ["/"])):
        raise HTTPException(422, "URL outside authorized website")
    run_id, job_id = uuid4(), uuid4()
    db.add(BackgroundJob(id=job_id, tenant_id=tenant, kind="ingestion.web", status="queued", progress=0))
    db.execute(import_runs.insert().values(
        id=run_id, tenant_id=tenant, source_id=data.source_id, job_id=job_id,
        kind="web", status="queued", checkpoint={
            "url": canonical(data.url), "max_pages": data.max_pages,
            "max_depth": data.max_depth, "delay": data.delay, "dry_run": data.dry_run,
        }, report=[],
    ))
    audit(db, user, "ingestion.web.started", run_id)
    db.commit()
    try:
        enqueue("process_web", run_id)
        db.execute(import_runs.update().where(import_runs.c.id == run_id).values(status="scheduled"))
        db.commit()
    except Exception:
        db.rollback()  # Recover with ingestion dispatcher; no lost job.
    return {"id": run_id, "job_id": job_id, "status": "queued"}

@router.post("/imports/telegram")
def telegram_instructions(data: TelegramStart,
                          user: User = Depends(require_roles("school_admin")),
                          db: Session = Depends(get_db)):
    tenant = school_id(user)
    source = db.execute(select(sources).where(
        sources.c.tenant_id == tenant, sources.c.id == data.source_id,
        sources.c.kind == "telegram")).mappings().first()
    if not source or not source["config"].get("active", False):
        raise HTTPException(404, "Source unavailable")
    return {"source_id": data.source_id, "mode": "new_messages_only",
            "status": "connected", "message": "Send documents to the authorized chat with the bot present."}

@router.post("/imports/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request, x_telegram_bot_api_secret_token: str | None = Header(None),
    db: Session = Depends(get_db),
):
    secret = os.getenv("SOMALOOM_TELEGRAM_WEBHOOK_SECRET")
    if not secret or not x_telegram_bot_api_secret_token or not hmac.compare_digest(
        secret, x_telegram_bot_api_secret_token
    ):
        raise HTTPException(403, "Webhook not authorized")
    body = await request.body()
    if len(body) > 100_000:
        raise HTTPException(413, "Webhook too large")
    import json
    try:
        update = json.loads(body)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid webhook payload") from None
    message = update.get("message") or update.get("channel_post") or {}
    chat = message.get("chat") or {}
    doc = message.get("document") or {}
    if not doc and message.get("photo"):
        doc = max(message["photo"], key=lambda p: p.get("file_size", 0))
    if not chat.get("id") or not message.get("message_id") or not doc.get("file_id"):
        return {"ok": True, "ignored": True}
    chat_id = str(chat["id"])
    candidates = db.execute(select(sources).where(sources.c.kind == "telegram")).mappings().all()
    matches = [s for s in candidates if s["config"].get("active") and s["config"].get("chat_id") == chat_id]
    if len(matches) != 1:
        return {"ok": True, "ignored": True}
    src = matches[0]
    tenant = src["tenant_id"]
    message_id = str(message["message_id"])
    existing = db.execute(select(telegram_receipts.c.id).where(
        telegram_receipts.c.tenant_id == tenant, telegram_receipts.c.chat_id == chat_id,
        telegram_receipts.c.message_id == message_id)).first()
    if existing:
        return {"ok": True, "duplicate": True}
    receipt_id, job_id = uuid4(), uuid4()
    db.add(BackgroundJob(id=job_id, tenant_id=tenant, kind="ingestion.telegram", status="queued", progress=0))
    db.execute(telegram_receipts.insert().values(
        id=receipt_id, tenant_id=tenant, source_id=src["id"], job_id=job_id,
        chat_id=chat_id, message_id=message_id, file_unique_id=doc.get("file_unique_id"),
        payload={"file_id": doc["file_id"], "filename": doc.get("file_name", "telegram-image.jpg"),
                 "file_size": doc.get("file_size"), "sender_id": (message.get("from") or {}).get("id")},
        state="queued",
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"ok": True, "duplicate": True}
    try:
        enqueue("process_telegram", receipt_id)
        db.execute(telegram_receipts.update().where(
            telegram_receipts.c.id == receipt_id,
            telegram_receipts.c.state == "queued",
        ).values(state="scheduled"))
        db.commit()
    except Exception:
        pass  # Recovery dispatcher will enqueue persisted receipts.
    return {"ok": True}

@router.get("/imports/{run_id}")
def get_import(run_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.execute(select(import_runs).where(
        import_runs.c.id == run_id, import_runs.c.tenant_id == school_id(user)
    )).mappings().first()
    if not row:
        raise HTTPException(404, "Import not found")
    return dict(row)

@router.post("/imports/{run_id}/retry", status_code=202)
def retry_import(run_id: UUID, user: User = Depends(require_roles("school_admin")),
                 db: Session = Depends(get_db)):
    tenant = school_id(user)
    run = db.execute(select(import_runs).where(
        import_runs.c.id == run_id, import_runs.c.tenant_id == tenant)).mappings().first()
    if not run:
        raise HTTPException(404, "Import not found")
    if run["status"] not in {"failed", "cancelled"}:
        raise HTTPException(409, "Import not retryable")
    db.execute(import_runs.update().where(import_runs.c.id == run_id).values(status="queued", error=None))
    job = db.get(BackgroundJob, run["job_id"])
    job.status, job.progress, job.finished_at, job.error = "queued", 0, None, None
    audit(db, user, "ingestion.web.retried", run_id)
    db.commit()
    try:
        enqueue("process_web", run_id)
    except Exception:
        pass
    return {"id": run_id, "status": "queued"}

@router.post("/imports/{run_id}/cancel")
def cancel_import(run_id: UUID, user: User = Depends(require_roles("school_admin")),
                  db: Session = Depends(get_db)):
    tenant = school_id(user)
    row = db.execute(select(import_runs).where(
        import_runs.c.id == run_id, import_runs.c.tenant_id == tenant)).mappings().first()
    if not row:
        raise HTTPException(404, "Import not found")
    db.execute(import_runs.update().where(import_runs.c.id == run_id).values(status="cancelled"))
    job = db.get(BackgroundJob, row["job_id"])
    job.status, job.finished_at = "cancelled", datetime.now(timezone.utc)
    audit(db, user, "ingestion.web.cancelled", run_id)
    db.commit()
    return {"id": run_id, "status": "cancelled"}

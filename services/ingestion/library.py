"""Tenant-scoped immutable resource library and validated uploads."""
import hashlib
import io
import os
import re
import shlex
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.models import AuditLog, BackgroundJob, resources, resource_versions
from app.core.storage import LocalObjectStore, S3ObjectStore
from services.ingestion.models import ingestion_outbox

MAX_BYTES = int(os.getenv("INGESTION_MAX_BYTES", str(20 * 1024 * 1024)))
MAX_FILES = int(os.getenv("INGESTION_MAX_FILES", "20"))
MAX_TENANT_BYTES = int(os.getenv("INGESTION_TENANT_MAX_BYTES", str(5 * 1024 ** 3)))
MAX_TENANT_RESOURCES = int(os.getenv("INGESTION_TENANT_MAX_RESOURCES", "50000"))
CHUNK = 1024 * 1024
MIMES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/html": ".html",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}

def object_store():
    bucket, kms = os.getenv("INGESTION_S3_BUCKET"), os.getenv("INGESTION_S3_KMS_KEY")
    if bucket:
        if not kms:
            raise RuntimeError("INGESTION_S3_KMS_KEY required for S3")
        return S3ObjectStore(bucket, kms)
    if get_settings().app_env == "production":
        raise RuntimeError("Production requires configured S3 durable storage")
    return LocalObjectStore(get_settings().storage_root)

def validate_file(data: bytes, declared_type: str | None = None) -> str:
    """Sniff exact supported types, rejecting renamed executables and dangerous archives."""
    if not data:
        raise HTTPException(422, "Empty file")
    if data.startswith(b"%PDF-"):
        mime = "application/pdf"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        mime = "image/jpeg"
    elif data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise ValueError("Not a DOCX")
                if len(names) > 2000 or any(
                    i.file_size > MAX_BYTES * 5 for i in z.infolist()
                ) or sum(i.file_size for i in z.infolist()) > MAX_BYTES * 10:
                    raise ValueError("Archive expansion limit")
                if any(i.flag_bits & 1 for i in z.infolist()):
                    raise ValueError("Encrypted archive")
        except (ValueError, zipfile.BadZipFile, RuntimeError):
            raise HTTPException(422, "Invalid or unsafe DOCX") from None
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "Unsupported or malformed file") from None
        if "\x00" in text or any(ord(c) < 9 for c in text):
            raise HTTPException(422, "Unsafe text content")
        trimmed = text.lstrip().lower()
        mime = "text/html" if trimmed.startswith(("<!doctype html", "<html")) else "text/plain"
    if declared_type and declared_type.split(";")[0].strip().lower() not in (
        mime, "application/octet-stream"
    ):
        raise HTTPException(422, "Declared content type does not match file signature")
    return mime

def safe_filename(filename: str | None, mime: str) -> str:
    name = (filename or "resource").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^a-zA-Z0-9._ -]", "_", name).strip(". ")[:120] or "resource"
    suffix = Path(name).suffix.lower()
    if suffix and suffix not in ({".jpg", ".jpeg"} if mime == "image/jpeg" else {MIMES[mime]}):
        raise HTTPException(422, "File extension does not match content")
    return name

async def read_upload(file: UploadFile) -> tuple[bytes, str, str, str]:
    digest = hashlib.sha256()
    length = 0
    with tempfile.SpooledTemporaryFile(max_size=CHUNK * 2) as temp:
        while chunk := await file.read(CHUNK):
            length += len(chunk)
            if length > MAX_BYTES:
                raise HTTPException(413, "File exceeds ingestion size limit")
            digest.update(chunk)
            temp.write(chunk)
        temp.seek(0)
        data = temp.read()
    mime = validate_file(data, file.content_type)
    return data, mime, safe_filename(file.filename, mime), digest.hexdigest()

def scan_original(data: bytes) -> str:
    """Optional ClamAV-compatible scanner command; mandatory in production."""
    command = os.getenv("INGESTION_SCANNER_COMMAND")
    if not command:
        if get_settings().app_env == "production":
            raise HTTPException(503, "File scanning unavailable")
        return "unscanned"
    with tempfile.NamedTemporaryFile(prefix="somaloom-scan-", delete=True) as temp:
        temp.write(data)
        temp.flush()
        try:
            result = subprocess.run(
                [*shlex.split(command), temp.name], capture_output=True, timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise HTTPException(503, "File scanning unavailable") from None
        if result.returncode == 1:
            raise HTTPException(422, "File rejected by antivirus")
        if result.returncode != 0:
            raise HTTPException(503, "File scanning unavailable")
    return "clean"

def _audit(db: Session, tenant_id: UUID, actor_id: UUID | None, action: str, target):
    db.add(AuditLog(tenant_id=tenant_id, actor_id=actor_id, action=action, target_id=str(target)))

def row_dict(row) -> dict:
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)

def get_resource(db: Session, tenant_id: UUID, resource_id: UUID):
    row = db.execute(
        select(resources).where(resources.c.tenant_id == tenant_id, resources.c.id == resource_id)
    ).mappings().first()
    if not row or row["provenance"].get("deleted_at"):
        raise HTTPException(404, "Resource not found")
    return dict(row)

def publish_version(
    db: Session, tenant_id: UUID, actor_id: UUID | None, data: bytes, mime: str,
    name: str, sha: str, title: str, license: str, source_uri: str, source_type: str,
    source_id: UUID | None = None, resource_id: UUID | None = None,
):
    """Persist original first; then atomically commit metadata, job and outbox event."""
    if not license.strip() or not source_uri.strip():
        raise HTTPException(422, "License and source URI required")
    # Serialize tenant writes so quota checks and imports stay atomic in PostgreSQL.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                   {"key": f"quota:{tenant_id}"})
    # Serialize identical content imports per tenant without prohibiting legal reimport
    # of originals whose prior resource has been soft-deleted.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                   {"key": f"{tenant_id}:{sha}"})
    same = db.execute(
        select(resource_versions.c.resource_id, resource_versions.c.id)
        .select_from(resource_versions.join(resources, and_(
            resources.c.id == resource_versions.c.resource_id,
            resources.c.tenant_id == resource_versions.c.tenant_id,
        )))
        .where(resource_versions.c.tenant_id == tenant_id,
               resource_versions.c.checksum_sha256 == sha,
               resources.c.provenance["deleted_at"].as_string().is_(None))
        .limit(1)
    ).first()
    if same and resource_id is None:
        # Preserve additional citation/licensing paths for a reused original.
        original = db.execute(select(resources).where(
            resources.c.id == same.resource_id, resources.c.tenant_id == tenant_id
        )).mappings().first()
        if original:
            provenance = dict(original["provenance"])
            existing = [provenance.get("source_uri")] + [
                s["source_uri"] for s in provenance.get("alternate_sources", [])
            ]
            if source_uri not in existing:
                alternatives = list(provenance.get("alternate_sources", []))
                alternatives.append({"source_uri": source_uri, "license": license,
                                     "source_type": source_type})
                provenance["alternate_sources"] = alternatives[-200:]
                db.execute(resources.update().where(
                    resources.c.id == same.resource_id, resources.c.tenant_id == tenant_id
                ).values(provenance=provenance))
                _audit(db, tenant_id, actor_id, "ingestion.resource.source_linked",
                       same.resource_id)
                db.commit()
        return {"resource_id": same.resource_id, "version_id": same.id, "duplicate": True}
    if resource_id is None and source_type in {"web", "telegram"}:
        previous = db.execute(select(resources).where(
            resources.c.tenant_id == tenant_id,
            resources.c.provenance["source_uri"].as_string() == source_uri,
        ).order_by(resources.c.created_at.desc())).mappings().first()
        if previous and not previous["provenance"].get("deleted_at"):
            resource_id = previous["id"]
    if resource_id:
        get_resource(db, tenant_id, resource_id)
        latest = db.scalar(select(func.max(resource_versions.c.version)).where(
            resource_versions.c.tenant_id == tenant_id,
            resource_versions.c.resource_id == resource_id,
        )) or 0
        if same and same.resource_id == resource_id:
            return {"resource_id": resource_id, "version_id": same.id, "duplicate": True}
        version = latest + 1
    else:
        resource_id, version = uuid4(), 1
    used = sum(int(p.get("file_size", 0)) for p in db.scalars(
        select(resource_versions.c.provenance).where(resource_versions.c.tenant_id == tenant_id)
    ))
    if used + len(data) > MAX_TENANT_BYTES:
        raise HTTPException(413, "School storage quota exceeded")
    if version == 1:
        count = db.scalar(select(func.count()).select_from(resources).where(
            resources.c.tenant_id == tenant_id
        ))
        if count >= MAX_TENANT_RESOURCES:
            raise HTTPException(413, "School resource count quota exceeded")
    version_id, job_id, event_id = uuid4(), uuid4(), uuid4()
    key = f"originals/{resource_id}/{version_id}/{MIMES[mime].lstrip('.')}"
    scan_status = scan_original(data)
    object_store().put(tenant_id, key, data)
    provenance = {
        "source_uri": source_uri, "source_type": source_type, "license": license,
        "checksum_sha256": sha, "imported_by": str(actor_id) if actor_id else None,
        "filename": name, "file_size": len(data), "created_at": datetime.now(timezone.utc).isoformat(),
        "scan_status": scan_status, "permissions": ["educational_reference"],
    }
    if not resource_id or not isinstance(resource_id, UUID):
        raise RuntimeError("Invalid resource id")
    if version == 1:
        db.execute(resources.insert().values(
            id=resource_id, tenant_id=tenant_id, title=title[:500],
            media_type=mime, provenance=provenance, import_source_id=source_id,
        ))
    else:
        db.execute(resources.update().where(
            resources.c.id == resource_id, resources.c.tenant_id == tenant_id
        ).values(title=title[:500], media_type=mime))
    db.execute(resource_versions.insert().values(
        id=version_id, tenant_id=tenant_id, resource_id=resource_id, version=version,
        object_key=key, checksum_sha256=sha, provenance=provenance,
    ))
    db.add(BackgroundJob(id=job_id, tenant_id=tenant_id, kind="ingestion.resource_available",
                         status="queued", progress=0))
    payload = {
        "event_id": str(event_id), "event_type": "resource.available", "tenant_id": str(tenant_id),
        "resource_id": str(resource_id), "version_id": str(version_id), "source_id": str(source_id) if source_id else None,
        "source_type": source_type, "object_key": key, "mime_type": mime, "sha256": sha,
        "title": title[:500], "license": license, "original_url": source_uri,
        "permissions": provenance["permissions"], "scan_status": scan_status,
    }
    db.execute(ingestion_outbox.insert().values(
        id=event_id, tenant_id=tenant_id, version_id=version_id, job_id=job_id,
        event_type="resource.available", payload=payload, state="pending", attempts=0,
    ))
    _audit(db, tenant_id, actor_id, "ingestion.resource.created", resource_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Version conflict; retry") from None
    return {"resource_id": resource_id, "version_id": version_id,
            "job_id": job_id, "duplicate": False}

def list_resources(db, tenant_id, query=None, mime=None, page=1, page_size=20):
    expr = select(resources).where(
        resources.c.tenant_id == tenant_id,
        resources.c.provenance["deleted_at"].as_string().is_(None),
    )
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        expr = expr.where(resources.c.title.ilike(f"%{escaped}%", escape="\\"))
    if mime:
        expr = expr.where(resources.c.media_type == mime)
    total = db.scalar(select(func.count()).select_from(expr.subquery()))
    rows = db.execute(expr.order_by(resources.c.created_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).mappings().all()
    return {"items": [dict(x) for x in rows], "page": page,
            "page_size": page_size, "total": total}

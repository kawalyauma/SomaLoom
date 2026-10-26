"""Extraction worker adapters to the existing RQ, SQLAlchemy and object-store contracts."""
from __future__ import annotations

import hashlib
import json
import logging
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update

from services.extraction.engine import ExtractionError, extract_bytes
from services.extraction.models import ExtractedDocument

LOG = logging.getLogger(__name__)
ENGINE = "multimodal-v1"


def normalized_key(version_id: UUID) -> str:
    return f"extractions/{version_id}/document.v1.json"


def object_store():
    from app.core.config import get_settings
    from app.core.storage import LocalObjectStore, S3ObjectStore

    settings = get_settings()
    # Production deployers must explicitly configure the cloud object store.
    import os
    bucket = os.environ.get("SOMALOOM_STORAGE_BUCKET")
    kms = os.environ.get("SOMALOOM_KMS_KEY_ID")
    if bool(bucket) != bool(kms):
        raise RuntimeError("Both S3 bucket and KMS key must be set")
    if bucket and kms:
        return S3ObjectStore(bucket, kms)
    return LocalObjectStore(settings.storage_root)


def put_idempotent(store, tenant_id: UUID, key: str, raw: bytes):
    """Object stores are create-only; a retry verifies existing bytes, never overwrites."""
    try:
        store.put(tenant_id, key, raw)
    except Exception:
        try:
            previous = store.get(tenant_id, key)
        except Exception:
            raise
        if hashlib.sha256(previous).digest() != hashlib.sha256(raw).digest():
            raise RuntimeError("Immutable object key collision") from None


def lookup_version(db, tenant_id: UUID, version_id: UUID):
    from app.core.models import resources, resource_versions

    return db.execute(
        select(resource_versions.c.id, resource_versions.c.resource_id,
               resource_versions.c.object_key, resource_versions.c.checksum_sha256,
               resources.c.media_type, resources.c.provenance)
        .join(resources,
              (resources.c.id == resource_versions.c.resource_id) &
              (resources.c.tenant_id == resource_versions.c.tenant_id))
        .where(resource_versions.c.id == version_id,
               resource_versions.c.tenant_id == tenant_id)
    ).mappings().first()


def create_extraction(db, tenant_id: UUID, version_id: UUID):
    """Idempotent entrypoint, also suitable for Agent 2 resource.available events.

    Transactional outbox / unique resource-version lock require Agent 1's
    additive migration proposal; a reconciliation command rescans queued jobs.
    """
    from app.core.models import BackgroundJob, extractions

    if not lookup_version(db, tenant_id, version_id):
        raise LookupError("Resource version not found")
    existing = db.execute(
        select(extractions.c.id, extractions.c.job_id)
        .where(extractions.c.resource_version_id == version_id,
               extractions.c.tenant_id == tenant_id,
               extractions.c.engine == ENGINE)
        .order_by(extractions.c.created_at)
    ).first()
    if existing:
        return existing[0], existing[1], False
    jid, eid = uuid4(), uuid4()
    db.add(BackgroundJob(id=jid, tenant_id=tenant_id, kind="extraction",
                         status="queued", progress=0))
    db.flush()
    db.execute(insert(extractions).values(id=eid, tenant_id=tenant_id,
                                         resource_version_id=version_id,
                                         job_id=jid, engine=ENGINE))
    db.commit()
    return eid, jid, True


def dispatch(job_id: UUID):
    """Enqueue after persisted job creation; safe to repeat under RQ job-id dedup."""
    from app.core.queue import queue

    return queue().enqueue(
        "services.extraction.jobs.process_extraction", str(job_id),
        job_id=f"extraction:{job_id}", job_timeout=900,
        result_ttl=3600, failure_ttl=86400,
    )


def accept_resource_available(event: dict) -> tuple[UUID, UUID]:
    """Internal trusted event adapter; tenant must come from Agent 2's DB event, not HTTP."""
    from app.core.database import SessionLocal

    if event.get("type") != "resource.available":
        raise ValueError("Incorrect resource event")
    tenant_id, version_id = UUID(event["tenant_id"]), UUID(event["version_id"])
    with SessionLocal() as db:
        eid, jid, _ = create_extraction(db, tenant_id, version_id)
    dispatch(jid)
    return eid, jid


def process_extraction(job_id: str) -> dict:
    """Importable RQ task; no untrusted paths, URLs or credentials in queue payload."""
    from app.core.database import SessionLocal
    from app.core.models import BackgroundJob, blocks, equations, extractions, visuals

    uid = UUID(job_id)
    with SessionLocal() as db:
        job = db.get(BackgroundJob, uid)
        if not job or job.kind != "extraction":
            raise LookupError("Extraction job unavailable")
        if job.status == "cancelled":
            return {"status": "cancelled"}
        if job.status == "succeeded":
            return {"status": "succeeded", "idempotent": True}
        link = db.execute(
            select(extractions.c.id, extractions.c.resource_version_id)
            .where(extractions.c.job_id == uid, extractions.c.tenant_id == job.tenant_id)
        ).first()
        if not link:
            raise LookupError("Extraction ownership mismatch")
        extraction_id, version_id = link
        version = lookup_version(db, job.tenant_id, version_id)
        if not version:
            raise LookupError("Source resource missing")
        job.status, job.progress, job.error = "running", 5, None
        db.commit()
        try:
            store = object_store()
            raw = store.get(job.tenant_id, version["object_key"])
            if hashlib.sha256(raw).hexdigest() != version["checksum_sha256"]:
                raise ExtractionError("Source checksum mismatch")
            license = (version["provenance"] or {}).get("license") or "unknown"
            doc = extract_bytes(
                raw, version["media_type"],
                resource_id=version["resource_id"], version_id=version_id,
                license=license,
                put_asset=lambda k, data: put_idempotent(store, job.tenant_id, k, data),
            )
            # A completed JSON is published immutably and can be reconstructed after crashes.
            encoded = doc.model_dump_json(indent=2).encode("utf-8")
            put_idempotent(store, job.tenant_id, normalized_key(version_id), encoded)
            # All DB rows and terminal status committed together, making retry idempotent.
            previous = db.scalar(select(blocks.c.id).where(
                blocks.c.extraction_id == extraction_id,
                blocks.c.tenant_id == job.tenant_id).limit(1))
            if not previous:
                for block in doc.blocks:
                    db.execute(insert(blocks).values(
                        id=block.id, tenant_id=job.tenant_id, extraction_id=extraction_id,
                        page=block.page, kind=block.type.value, text=block.text or "",
                        bbox=list(block.bbox) if block.bbox else None,
                    ))
                    if block.type.value == "equation" and block.latex:
                        db.execute(insert(equations).values(
                            id=uuid4(), tenant_id=job.tenant_id,
                            extraction_id=extraction_id, page=block.page,
                            latex=block.latex, confidence=block.confidence,
                        ))
                provenance = version["provenance"] or {}
                for asset in doc.assets:
                    db.execute(insert(visuals).values(
                        id=asset.id, tenant_id=job.tenant_id,
                        extraction_id=extraction_id, object_key=asset.object_key,
                        kind=asset.type.value, page=asset.page, caption=asset.caption,
                        provenance=provenance,
                    ))
            job.status, job.progress, job.error = "succeeded", 100, None
            from app.core.models import utcnow
            job.finished_at = utcnow()
            db.commit()
            return {"status": "succeeded", "partial": doc.partial,
                    "blocks": len(doc.blocks), "assets": len(doc.assets)}
        except Exception as exc:
            db.rollback()
            LOG.exception("Extraction failed for job %s", uid)
            job = db.get(BackgroundJob, uid)
            job.status = "failed"
            job.error = "extraction_failed:" + type(exc).__name__
            from app.core.models import utcnow
            job.finished_at = utcnow()
            db.commit()
            raise


def load_document(db, tenant_id: UUID, extraction_id: UUID) -> ExtractedDocument | None:
    from app.core.models import extractions

    version = db.execute(
        select(extractions.c.resource_version_id).where(
            extractions.c.id == extraction_id, extractions.c.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not version:
        return None
    store = object_store()
    try:
        raw = store.get(tenant_id, normalized_key(version))
    except (FileNotFoundError, KeyError):
        return None
    return ExtractedDocument.model_validate_json(raw)


def reconcile(limit: int = 100) -> int:
    """Requeue jobs stranded between the DB commit and Redis enqueue."""
    from app.core.database import SessionLocal
    from app.core.models import BackgroundJob

    if not 1 <= limit <= 1000:
        raise ValueError("limit must be in 1..1000")
    with SessionLocal() as db:
        rows = db.execute(select(BackgroundJob.id)
                          .where(BackgroundJob.kind == "extraction",
                                 BackgroundJob.status == "queued")
                          .limit(limit)).scalars().all()
    for uid in rows:
        dispatch(uid)
    return len(rows)

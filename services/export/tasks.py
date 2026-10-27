"""Durable, bounded RQ publishing; requests survive queue outages."""

from uuid import UUID

from app.core.database import SessionLocal
from app.core.models import BackgroundJob, School, User, exports, utcnow
from app.core.queue import queue
from app.core.storage import configured_store
from sqlalchemy import select

from services.export.models import requests


def dispatch_queued():
    with SessionLocal() as db:
        ids = db.scalars(
            select(BackgroundJob.id)
            .where(BackgroundJob.kind == "export", BackgroundJob.status == "queued")
            .limit(100)
        ).all()
    for jid in ids:
        work = queue()
        key = "export-" + str(jid)
        if work.fetch_job(key) is None:
            work.enqueue(run_export, str(jid), job_id=key, job_timeout=600, result_ttl=3600)
    return len(ids)


def run_export(job_id):
    from services.export.assets import resolver
    from services.export.publishing import export_docx, export_pdf
    from services.export.router import _latest_decision, _validate_evidence, _version

    with SessionLocal() as db:
        job = db.get(BackgroundJob, UUID(job_id), with_for_update=True)
        if not job or job.kind != "export" or job.status != "queued":
            return
        tenant = job.tenant_id
        row = (
            db.execute(
                select(exports).where(exports.c.job_id == job.id, exports.c.tenant_id == tenant)
            )
            .mappings()
            .one()
        )
        request = (
            db.execute(
                select(requests).where(
                    requests.c.export_id == row["id"], requests.c.tenant_id == tenant
                )
            )
            .mappings()
            .one()
        )
        job.status, job.progress = "running", 10
        db.commit()
        try:
            user = db.get(User, request["requested_by"])
            if not user or not user.active or user.tenant_id != tenant:
                raise ValueError("requester_unavailable")
            record = _version(db, row["document_version_id"], tenant)
            if _latest_decision(db, row["document_version_id"], tenant) != "approved":
                raise ValueError("approval_required")
            body = record["body"]
            _validate_evidence(db, tenant, body)
            if request["audience"] == "student" and record["document_type"] == "marking_guide":
                raise ValueError("teacher_only")
            renderer = export_pdf if row["format"] == "pdf" else export_docx
            content = renderer(
                {
                    "title": record["title"],
                    "document_type": record["document_type"],
                    "review_state": "approved",
                    "body": body,
                    "evidence_ids": body.get("evidence_ids", []),
                },
                branding={"school_name": db.get(School, tenant).name},
                audience=request["audience"],
                asset_resolver=resolver(db, tenant),
            )
            if len(content) > 30 * 1024 * 1024:
                raise ValueError("export_size_limit")
            db.refresh(job)
            if job.status == "cancelled":
                return
            key = f"published/{row['document_version_id']}/{request['audience']}/{row['id']}.{row['format']}"
            configured_store().put(tenant, key, content)
            db.execute(
                exports.update()
                .where(exports.c.id == row["id"], exports.c.tenant_id == tenant)
                .values(object_key=key)
            )
            job.status, job.progress, job.finished_at = "succeeded", 100, utcnow()
            db.commit()
        except Exception:
            db.rollback()
            job = db.get(BackgroundJob, UUID(job_id))
            job.status, job.error, job.finished_at = (
                "failed",
                "export_validation_or_render_failed",
                utcnow(),
            )
            db.commit()
            raise

"""Read-only, tenant-safe searchable-resource diagnostics.

Archived-only Telegram objects live outside this database and cannot be counted
here; null means unknown, not zero. Never infer that imported == indexed.
"""
from sqlalchemy import and_, func, select

from app.core.models import (
    BackgroundJob, blocks, extractions, resource_versions, resources, visuals,
)
from services.knowledge.models import items


def resource_coverage(db, school, *, page=1, page_size=25):
    if not (1 <= page <= 100000 and 1 <= page_size <= 100):
        raise ValueError("Invalid resource coverage page")
    current = (
        select(func.max(resource_versions.c.version))
        .where(
            resource_versions.c.tenant_id == school,
            resource_versions.c.resource_id == resources.c.id,
        )
        .correlate(resources)
        .scalar_subquery()
    )
    stmt = (
        select(
            resources.c.id.label("resource_id"),
            resources.c.title,
            resources.c.media_type,
            resources.c.provenance,
            resource_versions.c.id.label("version_id"),
            resource_versions.c.version,
        )
        .outerjoin(
            resource_versions,
            and_(
                resource_versions.c.resource_id == resources.c.id,
                resource_versions.c.tenant_id == school,
                resource_versions.c.version == current,
            ),
        )
        .where(resources.c.tenant_id == school)
        .order_by(resources.c.created_at.desc(), resources.c.id)
    )
    total = db.scalar(select(func.count()).select_from(resources).where(resources.c.tenant_id == school)) or 0
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).mappings().all()
    detail = []
    for row in rows:
        rights = row["provenance"] if isinstance(row["provenance"], dict) else {}
        version_id = row["version_id"]
        extraction_ids = []
        if version_id:
            extraction_ids = list(db.scalars(
                select(extractions.c.id).where(
                    extractions.c.tenant_id == school,
                    extractions.c.resource_version_id == version_id,
                )
            ).all())
        indexed_count = (db.scalar(select(func.count()).select_from(items).where(
            items.c.tenant_id == school,
            items.c.resource_version_id == version_id,
        )) or 0) if version_id else 0
        embedded_count = (db.scalar(select(func.count()).select_from(items).where(
            items.c.tenant_id == school,
            items.c.resource_version_id == version_id,
            items.c.embedding.is_not(None),
        )) or 0) if version_id else 0
        page_count = (db.scalar(select(func.count(func.distinct(blocks.c.page))).where(
            blocks.c.tenant_id == school, blocks.c.extraction_id.in_(extraction_ids),
        )) or 0) if extraction_ids else 0
        visual_count = (db.scalar(select(func.count()).select_from(visuals).where(
            visuals.c.tenant_id == school, visuals.c.extraction_id.in_(extraction_ids),
        )) or 0) if extraction_ids else 0
        reasons = []
        if rights.get("deleted_at"):
            reasons.append("deleted")
        if not rights.get("access_approved"):
            reasons.append("rights_not_approved")
        if not rights.get("license") or not rights.get("source_uri"):
            reasons.append("missing_license_or_source_uri")
        if version_id is None:
            reasons.append("no_resource_version")
        elif not extraction_ids:
            reasons.append("extraction_not_recorded")
        elif not indexed_count:
            reasons.append("index_empty")
        searchable = not reasons and indexed_count > 0
        detail.append({
            "resource_id": str(row["resource_id"]),
            "title": row["title"],
            "media_type": row["media_type"],
            "version_id": str(version_id) if version_id else None,
            "version": row["version"],
            "stage": "searchable" if searchable else "attention_required",
            "reasons": reasons,
            "extraction_records": len(extraction_ids),
            "pages_with_text_blocks": page_count,
            "indexed_chunks": indexed_count,
            "embedded_chunks": embedded_count,
            "visual_assets": visual_count,
            "embedding_coverage_percent": round(100 * embedded_count / indexed_count, 1)
            if indexed_count else 0,
        })
    failed = db.scalar(select(func.count()).select_from(BackgroundJob).where(
        BackgroundJob.tenant_id == school, BackgroundJob.status == "failed",
    )) or 0
    return {
        "items": detail, "total": total, "page": page, "page_size": page_size,
        "failed_background_jobs": failed,
        "archived_telegram_originals": None,
        "archived_telegram_note": (
            "Archive-only originals are stored outside this DB; reconcile with the "
            "Telegram archive service. They are not counted as imported/searchable."
        ),
        "limits": (
            "Pages with OCR failures and source confidence require a separate "
            "normalized-extraction audit; counts here are persisted DB facts."
        ),
    }

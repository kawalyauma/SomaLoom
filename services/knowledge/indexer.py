"""Incremental, rights-checked indexing of Agent 3's extracted source objects."""

import hashlib
import re
from uuid import UUID

from app.core.models import blocks, equations, extractions, resource_versions, resources, visuals
from sqlalchemy import and_, delete, select, update
from sqlalchemy.orm import Session

from services.knowledge.embeddings import MODEL, validate_vector
from services.knowledge.models import items, research_records, research_sources


def chunk_text(value: str, max_chars: int = 1200, overlap: int = 140) -> list[str]:
    if overlap < 0 or overlap >= max_chars or max_chars < 100:
        raise ValueError("Invalid chunk size")
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return []
    result = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            split = text.rfind(" ", start + max_chars // 2, end)
            if split > start:
                end = split
        fragment = text[start:end].strip()
        if fragment:
            result.append(fragment)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return result


def rights(resource) -> dict:
    info = resource["provenance"] or {}
    if not isinstance(info, dict) or not info.get("access_approved"):
        raise PermissionError("Source does not have explicit ingestion rights approval")
    if not info.get("license") or not info.get("source_uri"):
        raise ValueError("Resource requires license and original source URI")
    return info


def sources_for_version(db: Session, school: UUID, version_id: UUID):
    row = (
        db.execute(
            select(
                resource_versions,
                resources.c.title,
                resources.c.provenance.label("resource_rights"),
            )
            .join(
                resources,
                and_(
                    resources.c.id == resource_versions.c.resource_id,
                    resources.c.tenant_id == resource_versions.c.tenant_id,
                ),
            )
            .where(resource_versions.c.id == version_id, resource_versions.c.tenant_id == school)
        )
        .mappings()
        .first()
    )
    if not row:
        raise LookupError("Resource version not found")
    provenance = rights({"provenance": row["resource_rights"]})
    extra = (
        db.execute(
            select(extractions.c.id).where(
                extractions.c.tenant_id == school, extractions.c.resource_version_id == version_id
            )
        )
        .scalars()
        .all()
    )
    records = []
    if not extra:
        return row, provenance, records
    # Rich extraction confidence is retained in immutable normalized JSON. Never
    # promote uncertain OCR/equations to authoritative retrieval merely because
    # the minimal SQL block table has no confidence column.
    engines = db.scalars(select(extractions.c.engine).where(extractions.c.id.in_(extra))).all()
    blocked = set()
    if "multimodal-v1" in engines:
        from services.extraction.jobs import normalized_key, object_store
        from services.extraction.models import ExtractedDocument

        normalized = ExtractedDocument.model_validate_json(
            object_store().get(school, normalized_key(version_id))
        )
        blocked = {b.id for b in normalized.blocks if b.needs_review}
    for table, kind, field in [
        (blocks, "block", "text"),
        (visuals, "visual", "caption"),
        (equations, "equation", "latex"),
    ]:
        found = db.execute(
            select(table).where(table.c.tenant_id == school, table.c.extraction_id.in_(extra))
        ).mappings()
        for source in found:
            if source["id"] in blocked:
                continue
            if kind == "equation" and source["confidence"] < 0.85:
                continue
            if kind == "visual" and source["provenance"].get("needs_review", False):
                continue
            content = source[field] or ""
            if content.strip():
                records.append((kind, source["id"], source["page"], content))
    return row, provenance, records


def invalidate_research(db: Session, school: UUID, version_id: UUID):
    affected = select(research_sources.c.record_id).where(
        research_sources.c.tenant_id == school, research_sources.c.resource_version_id == version_id
    )
    db.execute(
        update(research_records)
        .where(research_records.c.tenant_id == school, research_records.c.id.in_(affected))
        .values(review_status="stale")
    )


def index_version(db: Session, school: UUID, version_id: UUID, embedder=None) -> dict:
    resource, prov, records = sources_for_version(db, school, version_id)
    if embedder is not None and (embedder.model != MODEL or embedder.dimensions != 1536):
        raise ValueError("Do not mix vector models/dimensions in the same index")
    existing = {
        (r["source_kind"], r["source_id"], r["chunk_no"]): r
        for r in db.execute(
            select(items).where(
                items.c.tenant_id == school, items.c.resource_version_id == version_id
            )
        )
        .mappings()
        .all()
    }
    seen = set()
    changed = 0
    for kind, source_id, page, body in records:
        for no, piece in enumerate(chunk_text(body)):
            key = (kind, source_id, no)
            seen.add(key)
            digest = hashlib.sha256(piece.encode()).hexdigest()
            prior = existing.get(key)
            if (
                prior
                and prior["fingerprint"] == digest
                and (embedder is None or prior["embedding_model"] == embedder.model)
            ):
                continue
            vector = embedder.embed([piece])[0] if embedder else None
            if vector is not None:
                validate_vector(vector)
            data = {
                "tenant_id": school,
                "resource_version_id": version_id,
                "resource_id": resource["resource_id"],
                "source_kind": kind,
                "source_id": source_id,
                "chunk_no": no,
                "text": piece,
                "page": page,
                "fingerprint": digest,
                "source_uri": prov["source_uri"],
                "license": prov["license"],
                "access_approved": True,
                "embedding_model": embedder.model if vector else None,
                "embedding": str(vector)
                if db.bind.dialect.name == "postgresql" and vector
                else vector,
                "metadata_json": {
                    k: prov[k]
                    for k in ("grade", "subject", "curriculum_id", "reliability")
                    if k in prov
                },
                "content_block_id": source_id if kind == "block" else None,
                "visual_asset_id": source_id if kind == "visual" else None,
                "equation_id": source_id if kind == "equation" else None,
            }
            if prior:
                db.execute(
                    update(items)
                    .where(items.c.id == prior["id"], items.c.tenant_id == school)
                    .values(**data)
                )
            else:
                db.execute(items.insert().values(**data))
            changed += 1
    for key, old in existing.items():
        if key not in seen:
            # Remove/expire evidence references before FK cascades discard source links.
            invalidate_research(db, school, version_id)
            db.execute(delete(items).where(items.c.id == old["id"], items.c.tenant_id == school))
            changed += 1
    if changed:
        invalidate_research(db, school, version_id)
    # A newly uploaded revision supersedes all older revisions of that resource.
    # Existing approved research anchored to older versions must be refreshed.
    older = (
        db.execute(
            select(resource_versions.c.id).where(
                resource_versions.c.tenant_id == school,
                resource_versions.c.resource_id == resource["resource_id"],
                resource_versions.c.version < resource["version"],
            )
        )
        .scalars()
        .all()
    )
    for superseded in older:
        invalidate_research(db, school, superseded)
    db.flush()
    return {
        "resource_version_id": str(version_id),
        "indexed": len(seen),
        "changed": changed,
        "embedding_model": embedder.model if embedder else None,
    }

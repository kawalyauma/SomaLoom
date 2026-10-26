"""Tenant-scoped persistence over Agent 1's established tables (no shadow schema)."""
from __future__ import annotations

import hashlib
import json
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import and_, func, insert, select
from sqlalchemy.orm import Session

from app.core.models import (
    BackgroundJob, blocks, documents, evidence, generation_evidence,
    generations, outcomes, versions,
)
from services.generation.schema import (
    EvidenceBundle, GenerationInput, GenerationStatus, Outcome, Passage, StructuredDraft,
)


def _fingerprint(data: GenerationInput) -> str:
    raw = data.model_dump_json(exclude_none=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def create_record(db: Session, tenant_id: UUID, actor_id: UUID,
                  payload: GenerationInput, key: str | None = None) -> tuple[UUID, UUID, bool]:
    """Request idempotency uses deterministic PK; caller handles unique collision/retry."""
    stable_id = uuid5(NAMESPACE_URL, f"somaloom:{tenant_id}:{actor_id}:{key}") if key else uuid4()
    fingerprint = _fingerprint(payload)
    existing = db.get(BackgroundJob, stable_id)
    if existing:
        if existing.tenant_id != tenant_id or existing.kind != "generation":
            raise ValueError("idempotency_conflict")
        old = db.execute(select(generations.c.id, generations.c.parameters)
                         .where(generations.c.job_id == stable_id,
                                generations.c.tenant_id == tenant_id)).first()
        if not old or old.parameters.get("fingerprint") != fingerprint:
            raise ValueError("idempotency_conflict")
        return stable_id, old.id, False
    background = BackgroundJob(id=stable_id, tenant_id=tenant_id,
                               kind="generation", status="queued", progress=0)
    db.add(background)
    db.flush()
    generated_id = uuid4()
    db.execute(insert(generations).values(
        id=generated_id, tenant_id=tenant_id, job_id=stable_id,
        requested_by=actor_id, document_type=payload.document_type.value,
        parameters={"request": payload.model_dump(mode="json"),
                    "fingerprint": fingerprint, "stage": "queued", "attempts": 0},
    ))
    db.commit()
    return stable_id, generated_id, True


def retrieve_evidence(db: Session, tenant_id: UUID,
                      request: GenerationInput) -> EvidenceBundle:
    """Temporary Agent 4 bridge. topic_ids must currently be actual outcome UUIDs.

    Agent 4 may replace this function with its permission-aware knowledge retriever,
    returning the exact EvidenceBundle contract. Never fabricate learning outcomes.
    """
    found = db.execute(select(outcomes).where(
        outcomes.c.tenant_id == tenant_id,
        outcomes.c.curriculum_id == request.curriculum_id,
        outcomes.c.id.in_(request.topic_ids),
    )).mappings().all()
    by_id = {r["id"]: Outcome(id=r["id"], code=r["code"],
                             description=r["description"]) for r in found}
    if set(request.topic_ids) != set(by_id):
        raise ValueError("topic_outcome_mapping_missing")
    rows = db.execute(
        select(evidence.c.id, evidence.c.outcome_id, evidence.c.quote,
               evidence.c.provenance)
        .where(evidence.c.tenant_id == tenant_id,
               evidence.c.outcome_id.in_(list(by_id)))
        .order_by(evidence.c.id).limit(300)
    ).mappings().all()
    allowed_licenses = request.resource_filters.get("licenses")
    if allowed_licenses is not None and (
        not isinstance(allowed_licenses, list) or
        len(allowed_licenses) > 30 or
        not all(isinstance(v, str) for v in allowed_licenses)
    ):
        raise ValueError("invalid_resource_filter")
    passages = []
    for r in rows:
        prov = r["provenance"] or {}
        if allowed_licenses is not None and prov.get("license") not in allowed_licenses:
            continue
        quote = (r["quote"] or "").strip()[:2500]
        if not quote:
            continue
        passages.append(Passage(
            id=r["id"], outcome_id=r["outcome_id"],
            quote=quote, source_title=prov.get("title"),
            source_uri=prov.get("source_uri"), license=prov.get("license"),
        ))
    return EvidenceBundle(outcomes=[by_id[x] for x in request.topic_ids],
                          passages=passages)


def owned_record(db: Session, generation_id: UUID, tenant_id: UUID):
    return db.execute(
        select(generations.c.id, generations.c.job_id, generations.c.parameters,
               BackgroundJob.status, BackgroundJob.progress, BackgroundJob.error)
        .join(BackgroundJob, BackgroundJob.id == generations.c.job_id)
        .where(generations.c.id == generation_id, generations.c.tenant_id == tenant_id,
               BackgroundJob.tenant_id == tenant_id)
    ).first()


def draft_record(db: Session, generation_id: UUID, tenant_id: UUID):
    return db.execute(
        select(versions.c.body, versions.c.version, documents.c.id)
        .join(documents, documents.c.id == versions.c.document_id)
        .where(documents.c.generation_job_id == generation_id,
               documents.c.tenant_id == tenant_id, versions.c.tenant_id == tenant_id)
        .order_by(versions.c.version.desc()).limit(1)
    ).first()


def save_draft(db: Session, tenant_id: UUID, generation_id: UUID,
               draft: StructuredDraft) -> UUID:
    old = draft_record(db, generation_id, tenant_id)
    if old:
        return old.id
    identifier = uuid4()
    first = draft.learning_outcomes[0]
    db.execute(insert(documents).values(
        id=identifier, tenant_id=tenant_id, generation_job_id=generation_id,
        title=f"{draft.document_type.value}: {first.description[:150]}",
        document_type=draft.document_type.value,
    ))
    db.execute(insert(versions).values(
        id=uuid4(), tenant_id=tenant_id, document_id=identifier,
        version=1, body=draft.model_dump(mode="json"),
    ))
    for ref in draft.references:
        db.execute(insert(generation_evidence).values(
            id=uuid4(), tenant_id=tenant_id,
            generation_job_id=generation_id, evidence_id=ref.id,
        ))
    return identifier


def update_progress(db: Session, job_id: UUID, tenant_id: UUID,
                    stage: str, progress: int) -> bool:
    job = db.get(BackgroundJob, job_id)
    if not job or job.tenant_id != tenant_id or job.status == "cancelled":
        return False
    if job.status in ("succeeded", "failed"):
        return False
    job.status = "running"
    job.progress = max(job.progress, min(99, progress))
    row = db.execute(select(generations).where(
        generations.c.job_id == job_id, generations.c.tenant_id == tenant_id
    )).mappings().first()
    if row:
        values = dict(row["parameters"] or {})
        values["stage"] = stage
        db.execute(generations.update().where(
            generations.c.id == row["id"], generations.c.tenant_id == tenant_id
        ).values(parameters=values))
    db.commit()
    return True


def finish(db: Session, job_id: UUID, tenant_id: UUID, status: str,
           error: str | None = None) -> bool:
    from datetime import datetime, timezone
    job = db.get(BackgroundJob, job_id)
    if not job or job.tenant_id != tenant_id or job.status == "cancelled":
        return False
    if job.status == "succeeded":
        return False
    job.status = status
    job.progress = 100 if status == "succeeded" else job.progress
    job.error = error  # classified code only, never raw provider output
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return True

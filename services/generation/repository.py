"""Tenant-scoped persistence over Agent 1's established tables (no shadow schema)."""

from __future__ import annotations

import hashlib
import os
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.core.models import (
    BackgroundJob,
    School,
    documents,
    evidence,
    generation_evidence,
    generations,
    outcomes,
    visuals,
    versions,
)
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from services.knowledge.high_recall import bound_generation_passages
from services.generation.schema import (
    EvidenceBundle,
    GenerationInput,
    Outcome,
    Passage,
    StructuredDraft,
    VisualReference,
)


def _fingerprint(data: GenerationInput) -> str:
    raw = data.model_dump_json(exclude_none=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def activity_event(parameters, stage, progress, status):
    from app.core.models import utcnow
    values = dict(parameters or {})
    events = list(values.get("activity", []))
    if not events or (events[-1]["stage"], events[-1]["status"]) != (stage, status):
        events.append({"stage": stage, "status": status, "progress": progress, "at": utcnow().isoformat()})
    values.update(stage=stage, activity=events[-100:])
    return values


def create_record(
    db: Session, tenant_id: UUID, actor_id: UUID, payload: GenerationInput, key: str | None = None
) -> tuple[UUID, UUID, bool]:
    """Request idempotency uses deterministic PK; caller handles unique collision/retry."""
    stable_id = uuid5(NAMESPACE_URL, f"somaloom:{tenant_id}:{actor_id}:{key}") if key else uuid4()
    fingerprint = _fingerprint(payload)
    existing = db.get(BackgroundJob, stable_id)
    if existing:
        if existing.tenant_id != tenant_id or existing.kind != "generation":
            raise ValueError("idempotency_conflict")
        old = db.execute(
            select(generations.c.id, generations.c.parameters).where(
                generations.c.job_id == stable_id, generations.c.tenant_id == tenant_id
            )
        ).first()
        if not old or old.parameters.get("fingerprint") != fingerprint:
            raise ValueError("idempotency_conflict")
        return stable_id, old.id, False
    # Serialize tenant submissions on PostgreSQL before enforcing cost/concurrency quota.
    if not db.get(School, tenant_id, with_for_update=True):
        raise ValueError("school_not_found")
    execution_mode="github"
    background = BackgroundJob(
        id=stable_id, tenant_id=tenant_id, kind="generation", status="queued", progress=0
    )
    db.add(background)
    db.flush()
    generated_id = uuid4()
    db.execute(
        insert(generations).values(
            id=generated_id,
            tenant_id=tenant_id,
            job_id=stable_id,
            requested_by=actor_id,
            document_type=payload.document_type.value,
            parameters=activity_event({
                "request": payload.model_dump(mode="json"),
                "fingerprint": fingerprint,
                "execution_mode": execution_mode,
                "attempts": 0,
            }, "queued", 0, "queued"),
        )
    )
    db.commit()
    return stable_id, generated_id, True


def retrieve_evidence(
    db: Session, tenant_id: UUID, request: GenerationInput, actor_id: UUID
) -> EvidenceBundle:
    """Resolve real topic mappings and current permission-checked Agent 4 evidence."""
    from app.core.models import User

    from services.curriculum.models import mappings, topics
    from services.knowledge.research import build_research
    from services.knowledge.retrieval import lookup

    topic_rows = (
        db.execute(
            select(topics).where(
                topics.c.id.in_(request.topic_ids),
                topics.c.tenant_id == tenant_id,
                topics.c.curriculum_id == request.curriculum_id,
            )
        )
        .mappings()
        .all()
    )
    if {r["id"] for r in topic_rows} != set(request.topic_ids):
        raise ValueError("topic_outcome_mapping_missing")
    actor = db.get(User, actor_id)
    if (
        not actor
        or not actor.active
        or actor.tenant_id != tenant_id
        or actor.role not in {"teacher", "school_admin"}
    ):
        raise ValueError("requester_unavailable")
    for topic in topic_rows:
        level = uuid5(NAMESPACE_URL, f"somaloom-level:{topic['curriculum_id']}:{topic['grade']}")
        subject = uuid5(
            NAMESPACE_URL, f"somaloom-subject:{topic['curriculum_id']}:{topic['subject']}"
        )
        if request.level_id != level or request.subject_id != subject:
            raise ValueError("topic_class_or_subject_mismatch")
    outcomes_found, passages, visual_references = {}, {}, {}
    license_filter = request.resource_filters.get("licenses")
    if license_filter is not None and (
        not isinstance(license_filter, list) or not all(isinstance(x, str) for x in license_filter)
    ):
        raise ValueError("invalid_resource_filter")
    for topic in topic_rows:
        rows = (
            db.execute(
                select(outcomes)
                .join(
                    mappings,
                    (mappings.c.outcome_id == outcomes.c.id)
                    & (mappings.c.tenant_id == outcomes.c.tenant_id),
                )
                .where(
                    mappings.c.topic_id == topic["id"],
                    mappings.c.tenant_id == tenant_id,
                    mappings.c.review_status == "approved",
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            outcomes_found[row["id"]] = Outcome(
                id=row["id"], code=row["code"], description=row["description"]
            )
        from services.schemes.service import source_passages
        for passage in source_passages(db, tenant_id, topic["id"], [r["id"] for r in rows]):
            if license_filter is None or passage["license"] in license_filter:
                passages[passage["id"]] = Passage(**passage)
        research = build_research(db, tenant_id, topic["id"], actor.id)
        for ev in research["evidence_links"]:
            # Only current, tenant-scoped, permission-approved and exactly
            # verifiable visual captions may be forwarded to the model.
            if ev.get("visual_asset_id") and ev.get("source_kind") == "visual":
                if license_filter is not None and ev["license"] not in license_filter:
                    continue
                if not lookup(db, tenant_id, UUID(ev["id"])):
                    continue
                asset = db.execute(
                    select(visuals).where(
                        visuals.c.id == UUID(ev["visual_asset_id"]),
                        visuals.c.tenant_id == tenant_id,
                    )
                ).mappings().first()
                if not asset or (asset["provenance"] or {}).get("needs_review"):
                    continue
                asset_id, outcome_id = asset["id"], UUID(ev["outcome_id"])
                visual_references[(asset_id, outcome_id)] = VisualReference(
                    id=asset_id,
                    outcome_id=outcome_id,
                    kind=asset["kind"],
                    caption=asset["caption"],
                    page=asset["page"],
                    source_uri=ev["source_uri"],
                    license=ev["license"],
                )
                continue
            # Text citations require a real content block.
            if not ev.get("content_block_id") or not lookup(db, tenant_id, UUID(ev["id"])):
                continue
            if license_filter is not None and ev["license"] not in license_filter:
                continue
            oid = UUID(ev["outcome_id"])
            # One stable evidence row per outcome/chunk, not a fictional citation.
            eid = uuid5(NAMESPACE_URL, f"somaloom-evidence:{tenant_id}:{oid}:{ev['id']}")
            provenance = {
                "source_uri": ev["source_uri"],
                "license": ev["license"],
                "page": ev["page"],
                "index_item_id": ev["id"],
                "resource_version_id": ev["resource_version_id"],
                "access_approved": True,
            }
            if not db.scalar(
                select(evidence.c.id).where(evidence.c.id == eid, evidence.c.tenant_id == tenant_id)
            ):
                db.execute(
                    evidence.insert().values(
                        id=eid,
                        tenant_id=tenant_id,
                        content_block_id=UUID(ev["content_block_id"]),
                        outcome_id=oid,
                        quote=ev["quote"],
                        provenance=provenance,
                    )
                )
            passages[eid] = Passage(
                id=eid,
                outcome_id=oid,
                quote=ev["quote"],
                source_title=ev.get("source_title") or topic["title"],
                source_uri=ev["source_uri"],
                license=ev["license"],
            )
    if not outcomes_found:
        raise ValueError("topic_outcome_mapping_missing")
    db.commit()
    targets = list(outcomes_found.values())
    selected_passages = bound_generation_passages(
        list(passages.values()), targets, max_total=80, max_per_outcome=6,
    )
    selected_outcomes = {p.outcome_id for p in selected_passages}
    selected_visuals = [
        visual for visual in visual_references.values()
        if visual.outcome_id in selected_outcomes
    ][:24]
    return EvidenceBundle(
        outcomes=targets,
        passages=selected_passages,
        visuals=selected_visuals,
    )


def owned_record(db: Session, generation_id: UUID, tenant_id: UUID):
    return db.execute(
        select(
            generations.c.id,
            generations.c.job_id,
            generations.c.requested_by,
            generations.c.parameters,
            BackgroundJob.status,
            BackgroundJob.progress,
            BackgroundJob.error,
        )
        .join(BackgroundJob, BackgroundJob.id == generations.c.job_id)
        .where(
            generations.c.id == generation_id,
            generations.c.tenant_id == tenant_id,
            BackgroundJob.tenant_id == tenant_id,
        )
    ).first()


def draft_record(db: Session, generation_id: UUID, tenant_id: UUID):
    return db.execute(
        select(versions.c.body, versions.c.version, documents.c.id)
        .join(documents, documents.c.id == versions.c.document_id)
        .where(
            documents.c.generation_job_id == generation_id,
            documents.c.tenant_id == tenant_id,
            versions.c.tenant_id == tenant_id,
        )
        .order_by(versions.c.version.desc())
        .limit(1)
    ).first()


def save_draft(db: Session, tenant_id: UUID, generation_id: UUID, draft: StructuredDraft) -> UUID:
    old = draft_record(db, generation_id, tenant_id)
    if old:
        return old.id
    identifier = uuid4()
    first = draft.learning_outcomes[0]
    db.execute(
        insert(documents).values(
            id=identifier,
            tenant_id=tenant_id,
            generation_job_id=generation_id,
            title=f"{draft.document_type.value}: {first.description[:150]}",
            document_type=draft.document_type.value,
        )
    )
    db.execute(
        insert(versions).values(
            id=uuid4(),
            tenant_id=tenant_id,
            document_id=identifier,
            version=1,
            body=__import__(
                "services.generation.documents", fromlist=["canonical_body"]
            ).canonical_body(
                draft.model_dump(mode="json"), [r.id for r in draft.references], seed=generation_id
            ),
        )
    )
    for ref in draft.references:
        db.execute(
            insert(generation_evidence).values(
                id=uuid4(),
                tenant_id=tenant_id,
                generation_job_id=generation_id,
                evidence_id=ref.id,
            )
        )
    return identifier


def update_progress(db: Session, job_id: UUID, tenant_id: UUID, stage: str, progress: int) -> bool:
    job = db.get(BackgroundJob, job_id)
    if not job or job.tenant_id != tenant_id or job.status == "cancelled":
        return False
    if job.status in ("succeeded", "failed"):
        return False
    job.status = "running"
    job.progress = max(job.progress, min(99, progress))
    row = (
        db.execute(
            select(generations).where(
                generations.c.job_id == job_id, generations.c.tenant_id == tenant_id
            )
        )
        .mappings()
        .first()
    )
    if row:
        values = activity_event(row["parameters"], stage, job.progress, "running")
        db.execute(
            generations.update()
            .where(generations.c.id == row["id"], generations.c.tenant_id == tenant_id)
            .values(parameters=values)
        )
    db.commit()
    return True


def finish(
    db: Session, job_id: UUID, tenant_id: UUID, status: str, error: str | None = None
) -> bool:
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
    row = db.execute(select(generations).where(generations.c.job_id == job_id, generations.c.tenant_id == tenant_id)).mappings().first()
    if row:
        db.execute(generations.update().where(generations.c.id == row["id"], generations.c.tenant_id == tenant_id).values(parameters={**activity_event(row["parameters"], status, job.progress, status), "last_failure":{"code":error,"at":job.finished_at.isoformat()} if error else row["parameters"].get("last_failure")}))
    db.commit()
    return True


def save_family(db, tenant_id, generation_id, kind, title, body):
    from services.rendering.document import validate_document

    validate_document(
        {"title": title, "body": body, "evidence_ids": body["evidence_ids"]},
        audience="teacher",
        strict_visuals=False,
    )
    old = draft_record(db, generation_id, tenant_id)
    if old:
        return old.id
    identifier = uuid4()
    db.execute(
        documents.insert().values(
            id=identifier,
            tenant_id=tenant_id,
            generation_job_id=generation_id,
            title=title[:500],
            document_type=kind,
        )
    )
    db.execute(
        versions.insert().values(
            id=uuid4(), tenant_id=tenant_id, document_id=identifier, version=1, body=body
        )
    )
    for eid in body["evidence_ids"]:
        db.execute(
            generation_evidence.insert().values(
                tenant_id=tenant_id, generation_job_id=generation_id, evidence_id=UUID(eid)
            )
        )
    return identifier

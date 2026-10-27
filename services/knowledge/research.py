"""Multi-source, curriculum-driven research records. No generative citation creation."""

import hashlib
import json
import os
import re
from collections import defaultdict
from uuid import UUID

from app.core.database import SessionLocal
from app.core.models import BackgroundJob, outcomes
from app.core.queue import queue
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from services.curriculum.models import mappings, topics
from services.knowledge.embeddings import Embeddings
from services.knowledge.indexer import index_version
from services.knowledge.models import outbox, research_records, research_sources
from services.knowledge.retrieval import search


def potential_conflicts(evidence: list[dict]) -> list[dict]:
    """Flag weak signals for human review; never resolve disagreements by majority."""
    findings = []
    by_concept = defaultdict(list)
    for ev in evidence:
        by_concept[(ev["outcome_id"], ev["concept"])].append(ev)
    for (outcome_id, concept), matches in by_concept.items():
        if len({e["resource_id"] for e in matches}) < 2:
            continue
        affirmative = [
            e
            for e in matches
            if not re.search(r"\b(is not|are not|does not|do not|cannot)\b", e["quote"].lower())
        ]
        negatives = [
            e
            for e in matches
            if re.search(r"\b(is not|are not|does not|do not|cannot)\b", e["quote"].lower())
        ]
        if affirmative and negatives:
            findings.append(
                {
                    "outcome_id": outcome_id,
                    "concept": concept,
                    "type": "possible_negation",
                    "requires_review": True,
                    "evidence_ids": [affirmative[0]["id"], negatives[0]["id"]],
                }
            )
        # Numeric variations may be legitimate; explicitly mark as provisional.
        numeric = defaultdict(list)
        for ev in matches:
            for n in re.findall(r"\b\d+(?:\.\d+)?\s*(?:°c|%|km|kg)\b", ev["quote"].lower()):
                numeric[n.strip()].append(ev)
        if len(numeric) > 1:
            ids = [entry[0]["id"] for entry in numeric.values()]
            findings.append(
                {
                    "outcome_id": outcome_id,
                    "concept": concept,
                    "type": "possible_numeric_disagreement",
                    "requires_review": True,
                    "evidence_ids": ids,
                }
            )
    return findings


def build_research(
    db: Session, school: UUID, topic_id: UUID, requested_by: UUID, embedder=None
) -> dict:
    topic = (
        db.execute(select(topics).where(topics.c.id == topic_id, topics.c.tenant_id == school))
        .mappings()
        .first()
    )
    if not topic:
        raise LookupError("Topic unavailable")
    approved = (
        db.execute(
            select(mappings, outcomes.c.code, outcomes.c.description)
            .join(
                outcomes,
                and_(
                    outcomes.c.id == mappings.c.outcome_id,
                    outcomes.c.tenant_id == mappings.c.tenant_id,
                ),
            )
            .where(
                mappings.c.topic_id == topic_id,
                mappings.c.tenant_id == school,
                mappings.c.review_status == "approved",
            )
        )
        .mappings()
        .all()
    )
    if not approved:
        raise ValueError("No approved outcomes mapped to this topic")
    coverage, links, used_items, versions = [], [], {}, set()
    revision = max(r["revision"] for r in approved)
    for row in approved:
        concepts = [v.strip() for v in (row["concepts"] or []) if isinstance(v, str) and v.strip()]
        if not concepts:
            concepts = [row["description"]]
        for concept in concepts[:20]:
            # Search independently per outcome concept; do not load entire textbooks.
            query = concept[:950]
            found = search(
                db,
                school,
                query,
                filters={"grade": topic["grade"], "subject": topic["subject"]},
                limit=8,
                embedder=embedder,
            )
            if not found:
                # Fallback broadens an overly restrictive library classification but not tenant/rights.
                found = search(db, school, concept[:950], limit=8, embedder=embedder)
            for ev in found:
                ev = {**ev, "outcome_id": str(row["outcome_id"]), "concept": concept}
                links.append(ev)
                used_items[ev["id"]] = ev
                versions.add(ev["resource_version_id"])
            unique_sources = len({e["resource_id"] for e in found})
            coverage.append(
                {
                    "outcome_id": str(row["outcome_id"]),
                    "code": row["code"],
                    "required": bool(row["required"]),
                    "official": row["origin"] == "official_candidate",
                    "concept": concept,
                    "status": "strong"
                    if unique_sources >= 2
                    else "partial"
                    if unique_sources == 1
                    else "missing",
                    "source_count": unique_sources,
                }
            )
    contradictions = potential_conflicts(links)
    total = len(coverage)
    sufficient = sum(c["status"] == "strong" for c in coverage)
    incomplete = sum(c["status"] == "partial" for c in coverage)
    # Measure coverage by outcomes, not gross number of chunks.
    confidence = round((sufficient + incomplete * 0.5) / total, 3) if total else 0
    digest = hashlib.sha256(
        json.dumps(sorted(e["fingerprint"] for e in used_items.values())).encode()
    ).hexdigest()
    bundle = {
        "schema_version": "1.0",
        "topic_id": str(topic_id),
        "curriculum_id": str(topic["curriculum_id"]),
        "tenant_id": str(school),
        "grade": topic["grade"],
        "subject": topic["subject"],
        "outline": [c["concept"] for c in coverage],
        "coverage": coverage,
        "gaps": [c for c in coverage if c["status"] != "strong"],
        "conflicts": contradictions,
        "confidence": confidence,
        "evidence_links": links,
        "visuals": [e for e in links if e["source_kind"] == "visual"],
        "equations": [e for e in links if e["source_kind"] == "equation"],
        "source_versions": sorted(versions),
        "index_version": digest,
        "curriculum_revision": revision,
        "review_status": "draft",
    }
    previous = db.scalar(
        select(func.max(research_records.c.content_version)).where(
            research_records.c.tenant_id == school, research_records.c.topic_id == topic_id
        )
    )
    record_id = db.execute(
        research_records.insert()
        .values(
            tenant_id=school,
            topic_id=topic_id,
            requested_by=requested_by,
            bundle=bundle,
            review_status="draft",
            index_version=digest,
            curriculum_revision=revision,
            content_version=(previous or 0) + 1,
        )
        .returning(research_records.c.id)
    ).scalar_one()
    for ev in used_items.values():
        db.execute(
            research_sources.insert().values(
                tenant_id=school,
                record_id=record_id,
                index_item_id=UUID(ev["id"]),
                resource_version_id=UUID(ev["resource_version_id"]),
            )
        )
    db.flush()
    return {"id": str(record_id), **bundle, "content_version": (previous or 0) + 1}


def submit(db: Session, school: UUID, user_id: UUID, kind: str, payload: dict) -> UUID:
    if kind not in {"topic_research", "knowledge_reindex"}:
        raise ValueError("Unsupported job kind")
    job = BackgroundJob(tenant_id=school, kind=kind, status="queued", progress=0)
    db.add(job)
    db.flush()
    db.execute(
        outbox.insert().values(
            tenant_id=school,
            job_id=job.id,
            status="pending",
            attempts=0,
            payload={**payload, "requested_by": str(user_id)},
        )
    )
    db.commit()
    return job.id


def dispatch_pending(db: Session, school: UUID | None = None, limit: int = 20) -> int:
    stmt = select(outbox).where(outbox.c.status == "pending")
    if school is not None:
        stmt = stmt.where(outbox.c.tenant_id == school)
    rows = db.execute(stmt.limit(limit).with_for_update(skip_locked=True)).mappings().all()
    sent = 0
    for row in rows:
        job_id = str(row["job_id"])
        work_queue = queue()
        if work_queue.fetch_job(job_id) is None:
            work_queue.enqueue(
                run_job, job_id, job_id=job_id, job_timeout=600, result_ttl=86400, failure_ttl=86400
            )
        db.execute(
            outbox.update()
            .where(outbox.c.id == row["id"], outbox.c.tenant_id == row["tenant_id"])
            .values(status="dispatched", attempts=row["attempts"] + 1)
        )
        sent += 1
    db.commit()
    return sent


def run_job(job_id: str):
    """RQ entry: only a persisted ID is received; tenant is loaded and revalidated."""
    with SessionLocal() as db:
        job = db.get(BackgroundJob, UUID(job_id))
        if not job:
            return
        order = (
            db.execute(
                select(outbox).where(outbox.c.job_id == job.id, outbox.c.tenant_id == job.tenant_id)
            )
            .mappings()
            .first()
        )
        if not order or job.status in ("succeeded", "cancelled"):
            return
        job.status, job.progress = "running", 10
        db.commit()
        try:
            payload = order["payload"]
            by = UUID(payload["requested_by"])
            school = job.tenant_id
            from app.core.models import User

            requester = db.get(User, by)
            if not requester or not requester.active or requester.tenant_id != school:
                raise PermissionError("Requester access revoked")
            embedder = Embeddings() if os.environ.get("SOMALOOM_EMBEDDINGS") == "openai" else None
            if job.kind == "knowledge_reindex":
                index_version(db, school, UUID(payload["resource_version_id"]), embedder)
            elif job.kind == "topic_research":
                build_research(db, school, UUID(payload["topic_id"]), by, embedder)
            else:
                raise ValueError("Unsupported job kind")
            job.status, job.progress = "succeeded", 100
            from app.core.models import utcnow

            job.finished_at = utcnow()
            db.commit()
        except Exception as exc:
            db.rollback()
            from app.core.models import utcnow

            job = db.get(BackgroundJob, UUID(job_id))
            job.status, job.progress = "failed", 100
            job.error = f"Processing failed ({type(exc).__name__})"
            job.finished_at = utcnow()
            db.commit()
            raise

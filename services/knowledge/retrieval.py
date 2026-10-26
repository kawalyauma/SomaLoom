"""Tenant- and rights-filtered keyword/semantic hybrid retrieval with real source pointers."""
import re
from collections import defaultdict
from uuid import UUID
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.orm import Session
from app.core.models import resources, resource_versions
from app.core.vector import Vector
from services.knowledge.embeddings import validate_vector
from services.knowledge.models import items

def fuse(rankings: list[list[dict]], k: int = 60) -> list[dict]:
    """Reciprocal rank fusion; duplicates get one result, without discarding provenance."""
    scores = defaultdict(float)
    found = {}
    for group in rankings:
        for rank, row in enumerate(group, 1):
            key = str(row["id"])
            scores[key] += 1.0 / (k + rank)
            found[key] = row
    return [{**found[key], "score": round(score, 6)}
            for key, score in sorted(scores.items(), key=lambda pair: -pair[1])]

def query_base(school: UUID, filters: dict | None = None):
    f = filters or {}
    if set(f) - {"grade", "subject", "curriculum_id", "resource_ids", "source_kind"}:
        raise ValueError("Unsupported search filters")
    # Join to the current resource and version: orphaned/stale/mis-scoped records are invisible.
    stmt = (select(items).join(resource_versions, and_(
        items.c.resource_version_id == resource_versions.c.id,
        items.c.tenant_id == resource_versions.c.tenant_id))
        .join(resources, and_(items.c.resource_id == resources.c.id,
             items.c.tenant_id == resources.c.tenant_id,
             resource_versions.c.resource_id == resources.c.id))
        .where(items.c.tenant_id == school, items.c.access_approved.is_(True),
               resources.c.provenance["access_approved"].as_boolean().is_(True)))
    # Never return archived versions after a newer upload exists.
    current_version = select(func.max(resource_versions.c.version)).where(
        resource_versions.c.resource_id == items.c.resource_id,
        resource_versions.c.tenant_id == school).correlate(items).scalar_subquery()
    stmt = stmt.where(resource_versions.c.version == current_version)
    if f.get("resource_ids"):
        stmt = stmt.where(items.c.resource_id.in_([UUID(str(x)) for x in f["resource_ids"][:100]]))
    for key in ("grade", "subject", "curriculum_id"):
        if f.get(key):
            stmt = stmt.where(items.c.metadata_json[key].as_string() == str(f[key]))
    if f.get("source_kind"):
        stmt = stmt.where(items.c.source_kind == f["source_kind"])
    return stmt

def as_evidence(row: dict, score: float = 0) -> dict:
    # quote is an exact substring from an indexed source item, never an LLM-generated paraphrase.
    text = row["text"]
    return {
        "id": str(row["id"]), "resource_id": str(row["resource_id"]),
        "resource_version_id": str(row["resource_version_id"]),
        "source_kind": row["source_kind"], "source_id": str(row["source_id"]),
        "content_block_id": str(row["content_block_id"]) if row["content_block_id"] else None,
        "visual_asset_id": str(row["visual_asset_id"]) if row["visual_asset_id"] else None,
        "equation_id": str(row["equation_id"]) if row["equation_id"] else None,
        "page": row["page"], "source_uri": row["source_uri"],
        "license": row["license"], "quote": text[:700],
        "fingerprint": row["fingerprint"], "score": score,
        "metadata": row["metadata_json"],
    }

def search(db: Session, school: UUID, query: str, *, filters: dict | None = None,
           limit: int = 10, embedder=None) -> list[dict]:
    if not query.strip() or len(query) > 1000:
        raise ValueError("Search query must be 1..1000 characters")
    if not (1 <= limit <= 50):
        raise ValueError("Limit must be 1..50")
    base = query_base(school, filters)
    engine = db.bind.dialect.name
    candidate_cap = min(200, max(30, limit * 5))
    lexical = []
    if engine == "postgresql":
        tokens = func.websearch_to_tsquery("simple", query)
        rank = func.ts_rank_cd(func.to_tsvector("simple", items.c.text), tokens)
        stmt = (base.where(or_(func.to_tsvector("simple", items.c.text).op("@@")(tokens),
                      items.c.text.ilike("%" + query.replace("%", r"\%").replace("_", r"\_") + "%")))
                .order_by(rank.desc()).limit(candidate_cap))
        lexical = [dict(r) for r in db.execute(stmt).mappings().all()]
    else:
        # SQLite is only for local tests; production uses PostgreSQL full-text indexes.
        words = [w.casefold() for w in re.findall(r"[\w]+", query) if w]
        stmt = base.limit(2000)
        candidates = [dict(r) for r in db.execute(stmt).mappings().all()]
        candidates.sort(key=lambda r: sum(r["text"].casefold().count(w) for w in words), reverse=True)
        lexical = [r for r in candidates if any(w in r["text"].casefold() for w in words)][:candidate_cap]
    semantic = []
    if embedder is not None and engine == "postgresql":
        vector = validate_vector(embedder.embed([query])[0])
        # Cast the parameter as vector(1536); column uses that exact same dimension.
        distance = items.c.embedding.op("<=>")(cast(str(vector), Vector(1536)))
        stmt = (base.where(items.c.embedding.is_not(None),
                  items.c.embedding_model == embedder.model).order_by(distance).limit(candidate_cap))
        semantic = [dict(r) for r in db.execute(stmt).mappings().all()]
    ranked = fuse([lexical, semantic])
    result = []
    seen_hashes, counts = set(), defaultdict(int)
    for row in ranked:
        # Reduce verbatim duplicate citations and single-book domination.
        if row["fingerprint"] in seen_hashes or counts[str(row["resource_id"])] >= 3:
            continue
        seen_hashes.add(row["fingerprint"])
        counts[str(row["resource_id"])] += 1
        result.append(as_evidence(row, row["score"]))
        if len(result) >= limit:
            break
    return result

def lookup(db: Session, school: UUID, item_id: UUID) -> dict | None:
    stmt = query_base(school).where(items.c.id == item_id)
    row = db.execute(stmt).mappings().first()
    return as_evidence(dict(row)) if row else None

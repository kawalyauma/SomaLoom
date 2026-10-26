"""Agent 4 synthetic integration and security smoke tests (SQLite lexical fallback)."""
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.main import app
from app.core.models import (
    BackgroundJob, blocks, curricula, equations, extractions,
    resource_versions, resources, visuals,
)
from conftest import sign_in
from services.curriculum.models import mappings, topics
from services.curriculum.router import router as curriculum_router
from services.knowledge.embeddings import validate_vector
from services.knowledge.indexer import chunk_text, index_version
from services.knowledge.models import items, research_records, research_sources
from services.knowledge.research import potential_conflicts
from services.knowledge.retrieval import fuse, lookup, search
from services.knowledge.router import router as knowledge_router

# Registration is normally owned by Agent 1; this test mounts the feature routers.
app.include_router(curriculum_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")

def make_version(db, school, text, *, approved=True, page=7, media="application/pdf",
                 diagram=False, equation=False):
    resource_id, version_id, extraction_id = uuid4(), uuid4(), uuid4()
    prov = {"source_uri": "https://example.org/synthetic-reference.pdf",
            "license": "synthetic-test-data", "access_approved": approved,
            "grade": "P5", "subject": "Science"}
    job = BackgroundJob(tenant_id=school, kind="extract")
    db.add(job)
    db.flush()
    db.execute(resources.insert().values(id=resource_id, tenant_id=school,
               title="Synthetic mock (not a textbook)", media_type=media, provenance=prov))
    db.execute(resource_versions.insert().values(id=version_id, tenant_id=school,
        resource_id=resource_id, version=1, object_key=f"synthetic/{version_id}",
        checksum_sha256="0" * 64, provenance=prov))
    db.execute(extractions.insert().values(id=extraction_id, tenant_id=school,
               resource_version_id=version_id, job_id=job.id, engine="synthetic"))
    block_id = uuid4()
    db.execute(blocks.insert().values(id=block_id, tenant_id=school,
               extraction_id=extraction_id, text=text, page=page, kind="paragraph"))
    if diagram:
        db.execute(visuals.insert().values(id=uuid4(), tenant_id=school,
            extraction_id=extraction_id, object_key="synthetic/diagram",
            kind="diagram", page=page + 1, caption="Digestive diagram shows stomach and intestine",
            provenance=prov))
    if equation:
        db.execute(equations.insert().values(id=uuid4(), tenant_id=school,
            extraction_id=extraction_id, page=page, latex=r"E = mc^2", confidence=0.95))
    db.flush()
    return version_id, block_id

def test_chunks_and_vectors():
    value = "First paragraph " * 150
    chunks = chunk_text(value, max_chars=160, overlap=20)
    assert len(chunks) > 2
    assert all(0 < len(c) <= 160 for c in chunks)
    assert chunk_text("") == []
    with pytest.raises(ValueError):
        validate_vector([0.0] * 384)
    assert validate_vector([0.0] * 1536) == [0.0] * 1536

def test_fusion_and_conflict_review():
    first = [{"id": "a", "resource_id": "1"}, {"id": "b", "resource_id": "2"}]
    ranked = fuse([first, [{"id": "b", "resource_id": "2"}]])
    assert ranked[0]["id"] == "b"
    samples = [
        {"id": "i1", "resource_id": "r1", "outcome_id": "o",
         "concept": "digestion", "quote": "It is important."},
        {"id": "i2", "resource_id": "r2", "outcome_id": "o",
         "concept": "digestion", "quote": "It is not important."},
    ]
    assert potential_conflicts(samples)[0]["requires_review"]

def test_rights_sources_and_tenant_isolation(db, accounts):
    schools, _ = accounts
    versions = []
    samples = [
        "Salivary amylase begins digestion of starch in the mouth.",
        "Peristalsis pushes swallowed food through the oesophagus.",
        "The small intestine absorbs nutrients through villi.",
        "The large intestine absorbs water.",
        "Digestion involves mechanical and chemical breakdown of food.",
    ]
    for idx, text in enumerate(samples):
        version, _ = make_version(db, schools[0].id, text,
            media="application/pdf" if idx % 2 == 0 else
                  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            diagram=idx == 0, equation=idx == 1)
        versions.append(version)
        summary = index_version(db, schools[0].id, version)
        assert summary["indexed"] >= 1
    db.commit()
    found = search(db, schools[0].id, "peristalsis")
    assert found and found[0]["page"] == 7
    assert found[0]["quote"] in samples[1]
    assert found[0]["content_block_id"]
    assert lookup(db, schools[1].id, found[0]["id"]) is None
    assert search(db, schools[1].id, "peristalsis") == []
    figures = search(db, schools[0].id, "digestive diagram")
    assert any(row["source_kind"] == "visual" and row["page"] == 8 for row in figures)
    maths = search(db, schools[0].id, "mc")
    assert any(row["source_kind"] == "equation" for row in maths)
    assert index_version(db, schools[0].id, versions[1])["changed"] == 0

def test_unapproved_source_denied(db, accounts):
    school = accounts[0][0].id
    version, _ = make_version(db, school, "Secret copied document", approved=False)
    with pytest.raises(PermissionError):
        index_version(db, school, version)

def test_stale_on_source_change(db, accounts):
    school, user = accounts[0][0].id, accounts[1][1]
    version, block_id = make_version(db, school, "Stomach produces digestive juices")
    index_version(db, school, version)
    indexed = db.execute(select(items).where(items.c.tenant_id == school)).mappings().first()
    curriculum_id, topic_id = uuid4(), uuid4()
    db.execute(curricula.insert().values(id=curriculum_id, tenant_id=school,
        country="Uganda", name="Synthetic P5 curriculum", version="2026"))
    db.execute(topics.insert().values(id=topic_id, tenant_id=school,
        curriculum_id=curriculum_id, level="Primary", grade="P5", subject="Science",
        unit="Human body", title="Digestion", kind="topic", sequence=1, prerequisites=[]))
    rid = uuid4()
    db.execute(research_records.insert().values(id=rid, tenant_id=school, topic_id=topic_id,
        requested_by=user.id, bundle={}, review_status="approved",
        index_version="before", curriculum_revision=1, content_version=1))
    db.execute(research_sources.insert().values(tenant_id=school, record_id=rid,
        resource_version_id=version, index_item_id=indexed["id"]))
    db.execute(blocks.update().where(blocks.c.id == block_id).values(
        text="Stomach churns food with digestive juices and enzymes"))
    assert index_version(db, school, version)["changed"] == 1
    status = db.scalar(select(research_records.c.review_status).where(
        research_records.c.id == rid))
    assert status == "stale"

def test_api_auth_scope_outcomes(client, accounts):
    schools, _ = accounts
    assert client.post("/api/v1/search", json={"query": "stomach"}).status_code == 401
    assert sign_in(client, "teacher0@example.org").status_code == 200
    assert client.get("/api/v1/curricula").status_code == 200
    assert client.post("/api/v1/search", json={
        "query": "stomach", "tenant_id": str(schools[1].id)}).status_code == 404
    assert client.post("/api/v1/search", json={
        "query": "stomach", "k": 51}).status_code == 422
    assert client.post("/api/v1/index/resource-versions/" + str(uuid4())).status_code == 403

def test_curriculum_approval_flow(client, db, accounts):
    school = accounts[0][0].id
    curriculum_id = uuid4()
    db.execute(curricula.insert().values(id=curriculum_id, tenant_id=school,
        country="Uganda", name="Synthetic mock curriculum", version="v1"))
    db.commit()
    headers = {"Origin": "http://localhost:3000"}
    sign_in(client, "school_admin0@example.org")
    topic = client.post(f"/api/v1/curricula/{curriculum_id}/topics", headers=headers,
        json={"level": "Primary", "grade": "P5", "subject": "Science",
              "unit": "Body", "title": "Digestion", "kind": "topic"})
    assert topic.status_code == 201, topic.text
    tid = topic.json()["id"]
    mapping = client.post(f"/api/v1/topics/{tid}/outcomes", headers=headers,
        json={"code": "S1", "description": "Identify digestive organs",
              "required": True, "origin": "official_candidate",
              "source_uri": "https://example.org/mock-curriculum",
              "source_license": "synthetic-test-data",
              "concepts": ["digestive organs", "their functions"]})
    assert mapping.status_code == 201, mapping.text
    assert mapping.json()["official"] is False
    sign_in(client, "reviewer0@example.org")
    answer = client.post(f"/api/v1/topics/{tid}/mappings/{mapping.json()['id']}/review",
        headers=headers, json={"status": "approved"})
    assert answer.status_code == 200, answer.text
    result = client.get(f"/api/v1/topics/{tid}/outcomes")
    assert result.json()["items"][0]["official"] is True

def test_authorized_curriculum_import_creates_drafts(client, accounts):
    sign_in(client, "school_admin0@example.org")
    data = {
        "name": "Uganda sample (synthetic)", "country": "Uganda", "version": "draft-1",
        "level": "Primary", "grade": "P5", "subject": "Science",
        "source_uri": "https://example.org/synthetic-curriculum",
        "source_license": "synthetic-test-data",
        "topics": [{
            "unit": "Human body", "title": "Digestion", "term": 1, "week": 3,
            "outcomes": [{
                "code": "P5.SC.D1", "description": "Explain the function of the stomach",
                "origin": "official_candidate", "required": True,
                "concepts": ["stomach", "digestion", "enzymes"]
            }]
        }]
    }
    resp = client.post("/api/v1/curricula/import",
                       headers={"Origin": "http://localhost:3000"}, json=data)
    assert resp.status_code == 201, resp.text
    assert resp.json()["official_outcomes"] == 0
    topics_result = client.get(f"/api/v1/curricula/{resp.json()['id']}/topics")
    assert topics_result.json()["total"] == 1
    outcomes_result = client.get(f"/api/v1/topics/{topics_result.json()['items'][0]['id']}/outcomes")
    assert outcomes_result.json()["items"][0]["official"] is False

"""High-recall regression checks on synthetic, explicitly non-official content."""
from sqlalchemy import select, update

from conftest import sign_in
from services.knowledge.diagnostics import resource_coverage
from services.knowledge.high_recall import (
    bound_generation_passages, query_variants, recall_at_k, select_evidence
)
from services.knowledge.indexer import index_version
from services.knowledge.models import items
from services.knowledge.retrieval import search
from test_agent04 import make_version


def test_education_synonyms_and_stable_budgets():
    q = query_variants("Vegetation", "East Africa", limit=8)
    assert q[0] == "Vegetation"
    assert any("plant cover" in x for x in q)
    assert any("grasslands" in x for x in q)
    assert len(q) <= 8
    assert query_variants("", "East Africa") == []
    assert query_variants("SST")[0] == "SST"
    assert any("social studies" in x for x in query_variants("SST"))
    assert recall_at_k(["x", "y"], {"y", "z"}, 2) == 0.5


def test_diversify_more_than_three_from_a_valid_source():
    hits = [
        dict(id=str(i), source_id=str(i), resource_id="book-a",
             resource_version_id="version-a", fingerprint=str(i),
             score=0.8 - i / 100)
        for i in range(7)
    ] + [
        dict(id="other", source_id="other", resource_id="book-b",
             resource_version_id="version-b", fingerprint="other", score=0.6)
    ]
    selected = select_evidence(hits + hits[:2], limit=20, max_per_resource=8)
    assert len(selected) == 8
    assert len({i["id"] for i in selected}) == 8
    assert sum(i["resource_id"] == "book-a" for i in selected) == 7
    assert selected[1]["resource_id"] == "book-b"


def test_missing_metadata_does_not_make_approved_source_unsearchable(db, accounts):
    school = accounts[0][0].id
    ver, _ = make_version(
        db, school,
        "East African vegetation includes savanna grasslands and forest plant cover."
    )
    index_version(db, school, ver)
    db.execute(update(items).where(
        items.c.tenant_id == school, items.c.resource_version_id == ver
    ).values(metadata_json={}))
    assert not search(db, school, "savanna", filters={
        "grade": "P7", "subject": "Social Studies"
    })
    broadened = search(db, school, "savanna", limit=8, max_per_resource=8)
    assert len(broadened) == 1
    assert broadened[0]["page"] == 7
    assert broadened[0]["resource_version_id"] == str(ver)


def test_admin_coverage_reports_real_index_counts_and_scope(client, db, accounts):
    schools, _ = accounts
    first = schools[0].id
    ver, _ = make_version(
        db, first, "SYNTHETIC P7 SST vegetation is plant cover in East Africa."
    )
    index_version(db, first, ver)
    result = resource_coverage(db, first, page_size=10)
    record = next(x for x in result["items"] if x["version_id"] == str(ver))
    assert record["stage"] == "searchable"
    assert record["indexed_chunks"] >= 1
    assert record["embedded_chunks"] == 0
    db.execute(update(items).where(items.c.resource_version_id == ver, items.c.tenant_id == first)
        .values(embedding=[0.0]*1536, embedding_model="text-embedding-3-small"))
    assert resource_coverage(db, first, page_size=10)["items"][0]["embedded_chunks"] == 1
    assert result["archived_telegram_originals"] is None
    assert all(x["resource_id"] for x in result["items"])
    assert resource_coverage(db, schools[1].id)["total"] == 0
    assert client.get("/api/v1/knowledge/resource-coverage").status_code == 401
    assert sign_in(client, "school_admin0@example.org").status_code == 200
    ok = client.get("/api/v1/knowledge/resource-coverage")
    assert ok.status_code == 200, ok.text
    assert ok.json()["total"] >= 1
    assert client.get("/api/v1/knowledge/resource-coverage?page_size=101").status_code == 422
    assert sign_in(client, "teacher0@example.org").status_code == 200
    assert client.get("/api/v1/knowledge/resource-coverage").status_code == 403


def test_denied_and_other_school_sources_never_return(db, accounts):
    school, other = accounts[0][0].id, accounts[0][1].id
    permitted, _ = make_version(db, school, "East Africa savanna vegetation", approved=True)
    make_version(db, school, "East Africa savanna vegetation", approved=False)
    foreign, _ = make_version(db, other, "East Africa savanna vegetation", approved=True)
    for version, owner in ((permitted, school), (foreign, other)):
        index_version(db, owner, version)
    assert [x["resource_version_id"] for x in search(
        db, school, "savanna", max_per_resource=8
    )] == [str(permitted)]


def test_synthetic_p7_sst_multiphase_recall_beats_one_phrase(db, accounts):
    """Synthetic relevance labels; NOT real textbook or independent Recall@50."""
    school = accounts[0][0].id
    first, _ = make_version(
        db, school,
        "Vegetation is plant cover in a region; natural forest covers mountains."
    )
    second, _ = make_version(
        db, school,
        "Savanna grasslands provide habitat across East African plains."
    )
    for version in (first, second):
        index_version(db, school, version)
    baseline = search(db, school, "vegetation", limit=20)
    baseline_ids = [x["resource_id"] for x in baseline]
    labels = set()
    for version in (first, second):
        labels.add(str(db.scalar(
            select(items.c.resource_id).where(items.c.resource_version_id == version)
        )))
    expanded = []
    for phrase in query_variants("vegetation", "East Africa", limit=8):
        expanded += search(db, school, phrase, limit=20, max_per_resource=8)
    selected = select_evidence(expanded, limit=40, max_per_resource=8)
    recovered = [x["resource_id"] for x in selected]
    before = recall_at_k(baseline_ids, labels, 50)
    after = recall_at_k(recovered, labels, 50)
    assert after >= before
    assert after == 1.0
    assert before < after


def test_teaching_ai_receives_verified_maps_without_approving_unverified_ones():
    """Schema and prompt contract; actual renderer storage URLs require separate QA."""
    import json
    from uuid import uuid4

    from services.templates.teaching.schemas import (
        CurriculumTarget, EvidenceBundle, EvidenceItem, TeachingSpec, VisualAssetEvidence
    )
    from services.templates.teaching.templates import build_prompt

    cid, lid, sid, tid, oid, eid, aid = [uuid4() for _ in range(7)]
    spec = TeachingSpec(
        type="lesson_notes", curriculum_id=cid, curriculum_version="synthetic-v1",
        level_id=lid, subject_id=sid, topic_ids=[tid], outcome_ids=[oid],
        depth="comprehensive",
    )
    bundle = EvidenceBundle(
        curriculum_id=cid, curriculum_version="synthetic-v1",
        outcomes=[CurriculumTarget(
            id=oid, curriculum_id=cid, level_id=lid, subject_id=sid,
            topic_id=tid, code="P7-SST-QA", description="Explain vegetation types"
        )],
        evidence=[EvidenceItem(
            id=eid, source_title="Synthetic CC0 source",
            source_uri="fixture://p7-sst", license="CC0-1.0",
            excerpt="The grasslands support diverse plants.", outcome_ids=[oid]
        )],
        visuals=[VisualAssetEvidence(
            asset_id=aid, outcome_id=oid, kind="map",
            caption="Synthetic map of vegetation", page=2,
            source_uri="fixture://p7-sst", license="CC0-1.0",
            permission_verified=True,
        )],
    )
    _, prompt = build_prompt(spec, bundle)
    parsed = json.loads(prompt)
    visual = parsed["curriculum_evidence"]["visuals"][0]
    assert visual["asset_id"] == str(aid)
    assert visual["permission_verified"] is True
    assert visual["source_uri"] == "fixture://p7-sst"


def test_generation_budget_keeps_all_outcomes_represented():
    from types import SimpleNamespace
    outcomes = [SimpleNamespace(id=str(i)) for i in range(5)]
    sources = [SimpleNamespace(outcome_id=str(i), quote=f"paragraph {i}-{j}")
               for i in range(5) for j in range(8)]
    selected = bound_generation_passages(sources, outcomes, max_total=10, max_per_outcome=6)
    assert len(selected) == 10
    assert {s.outcome_id for s in selected} == {str(i) for i in range(5)}
    assert selected[0].quote == "paragraph 0-0"
    assert selected[5].quote == "paragraph 0-1"

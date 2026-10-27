"""Real app/database/stream/RQ/renderer workflow with explicitly synthetic AI.

Run with TEST_DATABASE_URL and TEST_REDIS_URL for native service acceptance.
The model stub is NOT evidence of real provider acceptance or academic accuracy.
"""

import json
import os
import warnings
from io import BytesIO
from uuid import UUID, uuid4
from zipfile import ZipFile

import fakeredis
import pytest
from app.core.config import get_settings
from app.core.models import BackgroundJob, extractions
from app.main import app
from conftest import sign_in
from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from services.ai.provider import AIResult
from services.extraction.consumer import consume_once
from services.ingestion.jobs import deliver_outbox


class SyntheticProvider:
    async def generate(self, request):
        assert request.response_schema
        data = json.loads(request.prompt)
        if "spec" in data:
            spec, bundle = data["spec"], data["curriculum_evidence"]
            oid, eid = bundle["outcomes"][0]["id"], bundle["evidence"][0]["id"]
            body = {
                "title": "SYNTHETIC QA — water filtration",
                "sections": [
                    {
                        "key": key,
                        "title": key.replace("_", " ").title(),
                        "blocks": [
                            {
                                "kind": "paragraph",
                                "text": key
                                + ": A filter traps suspended particles; water may still contain pathogens.",
                                "citation_ids": [eid],
                                "outcome_ids": [oid],
                            }
                        ],
                    }
                    for key in data["required_section_keys"]
                ],
            }
            if spec["type"] == "lesson_plan":
                body["lesson_stages"] = [
                    {
                        "key": key,
                        "minutes": 10,
                        "teacher_actions": ["Show a safe filter model"],
                        "learner_actions": ["Observe suspended solids"],
                        "assessment": "Explain filtration limitations",
                        "differentiation": "Use labeled pictures",
                    }
                    for key in ["introduction", "development", "assessment", "conclusion"]
                ]
            if spec["type"] == "scheme_of_work":
                body["scheme_weeks"] = [
                    {
                        "week": w,
                        "topic_id": spec["topic_ids"][0],
                        "subtopics": ["Safe filtration model"],
                        "outcome_ids": [oid],
                        "periods": 2,
                        "methods": ["demonstration"],
                        "activities": ["Observe trapped particles"],
                        "resources": ["Sieve and safe sample"],
                        "assessment": "Explain limitations",
                        "citation_ids": [eid],
                    }
                    for w in [1, 2]
                ]
        else:
            spec, evidence = data["blueprint"], data["evidence"]
            body = {
                "questions": [
                    {
                        "type": "short_answer",
                        "curriculum_id": spec["curriculum_id"],
                        "level_id": spec["level_id"],
                        "subject_id": spec["subject_id"],
                        "topic_ids": spec["topic_ids"],
                        "outcome_ids": spec["outcome_ids"],
                        "difficulty": "medium",
                        "cognitive_target": "understand",
                        "stem": text,
                        "marks": 5,
                        "estimated_minutes": 5,
                        "answer": {
                            "acceptable_answers": ["PRIVATE TEACHER ANSWER: suspended solids"]
                        },
                        "provenance": "ai_generated",
                        "source_refs": [
                            {
                                "evidence_id": evidence[0]["evidence_id"],
                                "source_uri": evidence[0]["source_uri"],
                                "license": evidence[0]["license"],
                            }
                        ],
                    }
                    for text in [
                        "What can a filter trap from water?",
                        "Why is filtered water not necessarily safe to drink?",
                    ]
                ]
            }
        return AIResult(text=json.dumps(body), provider="synthetic-test-only", model="fixture")


def test_real_app_routes_and_cors(client):
    app.openapi_schema = None
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message="Duplicate Operation ID.*")
        spec = app.openapi()
    for path in [
        "resources/uploads",
        "extractions",
        "curricula",
        "search",
        "generations",
        "question-bank",
        "assessments",
        "documents",
        "exports",
    ]:
        assert f"/api/v1/{path}" in spec["paths"]
    for method in ["PATCH", "PUT", "DELETE"]:
        response = client.options(
            "/api/v1/resources/" + str(uuid4()),
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": method},
        )
        assert response.status_code == 200
    denied = client.options(
        "/api/v1/resources/" + str(uuid4()),
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "DELETE"},
    )
    assert denied.status_code == 400


@pytest.mark.parametrize(
    "kind", ["lesson_notes", "scheme_of_work", "lesson_plan", "teacher_guide", "exam", "test"]
)
def test_upload_stream_rq_research_generate_review_export(
    kind, client, accounts, db, monkeypatch, tmp_path
):
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "ai_provider", "api")
    monkeypatch.setattr("app.routes.generation.provider_available", lambda _: True)
    monkeypatch.setattr(
        "services.generation.tasks.configured_provider", lambda _: SyntheticProvider()
    )
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    for module in [
        "app.core.database",
        "services.ingestion.jobs",
        "services.generation.tasks",
        "services.knowledge.research",
        "services.export.tasks",
    ]:
        monkeypatch.setattr(module + ".SessionLocal", factory)
    redis = (
        Redis.from_url(os.environ["TEST_REDIS_URL"])
        if os.getenv("TEST_REDIS_URL")
        else fakeredis.FakeRedis()
    )
    # Dedicated random queue and stream database (TEST_REDIS_URL must be disposable).
    work = Queue("somaloom-qa-" + uuid4().hex, connection=redis)
    monkeypatch.setattr("app.core.queue.queue", lambda: work)
    monkeypatch.setattr("services.ingestion.jobs.queue", lambda: work)
    monkeypatch.setattr("services.generation.tasks.queue", lambda: work)
    monkeypatch.setattr("services.export.tasks.queue", lambda: work)
    monkeypatch.setattr("services.ingestion.jobs.redis_connection", lambda: redis)
    redis.delete("somaloom:resource.available")
    client.headers["Origin"] = "http://localhost:3000"
    assert sign_in(client, "school_admin0@example.org").status_code == 200
    imported = client.post(
        "/api/v1/curricula/import",
        json={
            "name": "SYNTHETIC teacher-authored P5 science QA",
            "country": "Uganda",
            "version": "qa-2026",
            "level": "Primary",
            "grade": "P5",
            "subject": "Science",
            "source_uri": "fixture://owned-curriculum",
            "source_license": "CC0-1.0",
            "topics": [
                {
                    "unit": "Water",
                    "title": "Filtration",
                    "outcomes": [
                        {
                            "code": "QA-FILTER",
                            "description": "Describe water filtration",
                            "origin": "enrichment",
                            "concepts": ["filtration"],
                        }
                    ],
                }
            ],
        },
    )
    assert imported.status_code == 201, imported.text
    cid = imported.json()["id"]
    topic = client.get(f"/api/v1/curricula/{cid}/topics").json()["items"][0]
    tid = topic["id"]
    mapping = client.get(f"/api/v1/topics/{tid}/outcomes").json()["items"][0]
    approval = client.post(
        f"/api/v1/topics/{tid}/mappings/{mapping['id']}/review", json={"status": "approved"}
    )
    assert approval.status_code == 200, approval.text
    for number, sentence in enumerate(
        [
            "Filtration traps suspended particles in a filter. Water may still contain pathogens.",
            "A filtration model uses a sieve to separate suspended solids. Filtration alone does not ensure drinking safety.",
        ]
    ):
        raw = f"<!doctype html><html><h1>Owned QA science {number}</h1><p>{sentence}</p></html>".encode()
        upload = client.post(
            "/api/v1/resources/uploads",
            data={"license": "CC0-1.0"},
            files=[("files", (f"owned-{number}.html", raw, "text/html"))],
        )
        assert upload.status_code == 201, upload.text
        from services.ingestion.models import ingestion_outbox

        event = (
            db.execute(
                select(ingestion_outbox).where(
                    ingestion_outbox.c.version_id == UUID(upload.json()["items"][0]["version_id"])
                )
            )
            .mappings()
            .one()
        )
        deliver_outbox(str(event["id"]))
    assert consume_once(redis) == 2
    # Replay stream entries: deduplication is by DB extraction/version and event receipt.
    assert consume_once(redis) == 0
    SimpleWorker([work], connection=redis).work(burst=True)
    db.expire_all()
    assert (
        db.scalar(select(BackgroundJob.status).where(BackgroundJob.kind == "extraction").limit(1))
        == "succeeded"
    )
    assert len(db.execute(select(extractions)).all()) == 2
    options = {
        "depth": "concise",
        "duration_minutes": 40,
        "question_count": 2,
        "total_marks": 10,
        "weeks": 2,
        "periods_per_week": 5,
        "period_minutes": 40,
        "term": "QA term",
        "academic_year": "2026",
        "calendar": {"starts_on": "2026-10-26", "ends_on": "2026-11-06"},
    }
    assert sign_in(client, "teacher0@example.org").status_code == 200
    generated = client.post(
        "/api/v1/generations",
        json={
            "document_type": kind,
            "curriculum_id": cid,
            "level_id": topic["level_id"],
            "subject_id": topic["subject_id"],
            "topic_ids": [tid],
            "options": options,
        },
    )
    assert generated.status_code == 202, generated.text
    gid = generated.json()["id"]
    SimpleWorker([work], connection=redis).work(burst=True)
    db.expire_all()
    state = client.get(f"/api/v1/generations/{gid}").json()
    assert state["status"] == "succeeded", state
    from services.knowledge.models import research_records

    teacher = next(u for u in accounts[1] if u.email == "teacher0@example.org")
    assert (
        db.scalar(
            select(research_records.c.requested_by).where(research_records.c.topic_id == UUID(tid))
        )
        == teacher.id
    )
    if kind == "lesson_notes":
        from services.generation.repository import retrieve_evidence
        from services.generation.schema import GenerationInput

        bad_context = GenerationInput(
            document_type=kind,
            curriculum_id=cid,
            level_id=uuid4(),
            subject_id=topic["subject_id"],
            topic_ids=[tid],
        )
        with pytest.raises(ValueError, match="topic_class_or_subject_mismatch"):
            retrieve_evidence(db, teacher.tenant_id, bad_context, teacher.id)
    draft = client.get(f"/api/v1/generations/{gid}/draft").json()
    doc_id, version_id = draft["document_id"], draft["document"]["id"]
    assert draft["document"]["body"]["evidence_ids"]
    assert (
        client.post(
            "/api/v1/exports", json={"document_version_id": version_id, "format": "docx"}
        ).status_code
        == 409
    )
    assert sign_in(client, "reviewer0@example.org").status_code == 200
    reviewed = client.post(
        f"/api/v1/documents/{doc_id}/versions/{version_id}/review",
        json={
            "decision": "approved",
            "comments": "Synthetic QA structure reviewed; no academic acceptance claimed.",
            "citations_checked": True,
            "mathematics_checked": True,
            "licensing_checked": True,
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    for fmt in ["pdf", "docx"]:
        exported = client.post(
            "/api/v1/exports",
            json={"document_version_id": version_id, "format": fmt, "asynchronous": fmt == "docx"},
        )
        assert exported.status_code == (202 if fmt == "docx" else 201), exported.text
        if fmt == "docx":
            SimpleWorker([work], connection=redis).work(burst=True)
            db.expire_all()
            status = client.get("/api/v1/jobs/" + exported.json()["job_id"]).json()
            assert status["status"] == "succeeded", status
        download = client.get(exported.json()["download_url"])
        assert download.status_code == 200 and len(download.content) > 1000
        if fmt == "docx":
            with ZipFile(BytesIO(download.content)) as archive:
                assert b"PRIVATE TEACHER ANSWER" not in archive.read("word/document.xml")
        else:
            import pymupdf

            with pymupdf.open(stream=download.content, filetype="pdf") as pdf:
                assert len(pdf) >= 1
                assert "PRIVATE TEACHER ANSWER" not in "".join(p.get_text() for p in pdf)
    assert sign_in(client, "teacher1@example.org").status_code == 200
    assert client.get(f"/api/v1/generations/{gid}/draft").status_code == 404
    assert client.get(exported.json()["download_url"]).status_code == 404

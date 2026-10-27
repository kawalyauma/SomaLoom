"""Agent 8 local integration tests using Agent 1's SQLite/auth fixtures."""

from io import BytesIO
from uuid import uuid4

from app.core.config import get_settings
from app.core.models import (
    BackgroundJob,
    documents,
    generations,
    versions,
)
from conftest import sign_in
from sqlalchemy import insert


def seed_document(db, school, user):
    job = BackgroundJob(tenant_id=school.id, kind="generation", status="succeeded", progress=100)
    db.add(job)
    db.flush()
    gen_id, doc_id, version_id = uuid4(), uuid4(), uuid4()
    db.execute(
        insert(generations).values(
            id=gen_id,
            tenant_id=school.id,
            job_id=job.id,
            document_type="test",
            parameters={},
            requested_by=user.id,
        )
    )
    db.execute(
        insert(documents).values(
            id=doc_id,
            tenant_id=school.id,
            generation_job_id=gen_id,
            title="Primary Maths",
            document_type="test",
        )
    )
    body = {
        "evidence_ids": [],
        "sections": [
            {
                "title": "Addition",
                "blocks": [
                    {
                        "id": "question-1",
                        "type": "question",
                        "text": "Find 2 + 2.",
                        "answer": "SECRET ANSWER",
                    },
                    {
                        "id": "answer-1",
                        "type": "answer",
                        "text": "SECRET ANSWER",
                        "audience": "teacher",
                    },
                    {"id": "equation-1", "type": "equation", "latex": r"\frac{1}{2}+x^2"},
                ],
            }
        ],
    }
    db.execute(
        insert(versions).values(
            id=version_id, tenant_id=school.id, document_id=doc_id, version=1, body=body
        )
    )
    db.commit()
    return doc_id, version_id, body


def test_school_scoping_and_version_save(client, db, accounts):
    schools, users = accounts
    teacher = next(u for u in users if u.role == "teacher" and u.tenant_id == schools[0].id)
    other = next(u for u in users if u.role == "teacher" and u.tenant_id == schools[1].id)
    doc_id, version_id, body = seed_document(db, schools[0], teacher)
    assert sign_in(client, teacher.email).status_code == 200
    records = client.get("/api/v1/documents")
    assert records.status_code == 200 and records.json()["total"] == 1
    assert client.get(f"/api/v1/documents/{doc_id}/versions").json()["total"] == 1
    assert client.get(f"/api/v1/documents/{doc_id}/versions/{version_id}").status_code == 200
    headers = {"Origin": "http://localhost:3000"}
    updated = client.post(
        f"/api/v1/documents/{doc_id}/versions",
        json={"expected_version": 1, "body": body},
        headers=headers,
    )
    assert updated.status_code == 201, updated.text
    assert updated.json()["version"] == 2
    stale = client.post(
        f"/api/v1/documents/{doc_id}/versions",
        json={"expected_version": 1, "body": body},
        headers=headers,
    )
    assert stale.status_code == 409
    assert sign_in(client, other.email).status_code == 200
    assert client.get(f"/api/v1/documents/{doc_id}/versions").status_code == 404
    assert client.get(f"/api/v1/documents/{doc_id}/versions/{version_id}").status_code == 404


def test_review_approval_and_audience_export(client, db, accounts, tmp_path, monkeypatch):
    schools, users = accounts
    teacher = next(u for u in users if u.role == "teacher" and u.tenant_id == schools[0].id)
    reviewer = next(u for u in users if u.role == "reviewer" and u.tenant_id == schools[0].id)
    doc_id, version_id, _ = seed_document(db, schools[0], teacher)
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    headers = {"Origin": "http://localhost:3000"}
    payload = {
        "decision": "approved",
        "comments": "All learning facts and answers have been verified.",
        "citations_checked": True,
        "mathematics_checked": True,
        "licensing_checked": True,
    }
    assert sign_in(client, teacher.email).status_code == 200
    assert (
        client.post(
            f"/api/v1/documents/{doc_id}/versions/{version_id}/review",
            json=payload,
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/exports",
            json={"document_version_id": str(version_id), "format": "pdf"},
            headers=headers,
        ).status_code
        == 409
    )
    assert sign_in(client, reviewer.email).status_code == 200
    invalid = client.post(
        f"/api/v1/documents/{doc_id}/versions/{version_id}/review",
        json={**payload, "mathematics_checked": False},
        headers=headers,
    )
    assert invalid.status_code == 422
    approve = client.post(
        f"/api/v1/documents/{doc_id}/versions/{version_id}/review", json=payload, headers=headers
    )
    assert approve.status_code == 201, approve.text
    result = client.post(
        "/api/v1/exports",
        json={"document_version_id": str(version_id), "format": "pdf", "audience": "student"},
        headers=headers,
    )
    assert result.status_code == 201, result.text
    binary = client.get(result.json()["download_url"])
    assert binary.status_code == 200 and binary.content.startswith(b"%PDF")
    from pypdf import PdfReader

    text = "".join(page.extract_text() or "" for page in PdfReader(BytesIO(binary.content)).pages)
    assert "Find 2 + 2." in text
    assert "SECRET ANSWER" not in text


def test_fabricated_evidence_cannot_be_approved(client, db, accounts):
    schools, users = accounts
    teacher = next(u for u in users if u.role == "teacher" and u.tenant_id == schools[0].id)
    reviewer = next(u for u in users if u.role == "reviewer" and u.tenant_id == schools[0].id)
    document_id, version_id, body = seed_document(db, schools[0], teacher)
    fabricated_id = str(uuid4())
    body["evidence_ids"] = [fabricated_id]
    body["sections"][0]["blocks"][0]["citations"] = [fabricated_id]
    db.execute(versions.update().where(versions.c.id == version_id).values(body=body))
    db.commit()
    assert sign_in(client, reviewer.email).status_code == 200
    result = client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/review",
        headers={"Origin": "http://localhost:3000"},
        json={
            "decision": "approved",
            "comments": "Reviewed all source attributions.",
            "citations_checked": True,
            "mathematics_checked": True,
            "licensing_checked": True,
        },
    )
    assert result.status_code == 422
    assert "Evidence" in result.text

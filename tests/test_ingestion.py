"""Agent 2 integration tests: use Agent 1's SQLite/auth fixtures, no live tokens."""

from uuid import uuid4

import pytest
from app.core.storage import LocalObjectStore
from sqlalchemy import select

from services.ingestion import models  # noqa: F401 - register feature tables before fixture create_all
from services.ingestion.crawler import allowed, canonical, safe_addresses
from services.ingestion.library import safe_filename, validate_file
from services.ingestion.models import ingestion_outbox, telegram_receipts

PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"


def signin(client, role="school_admin", school=0):
    res = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:3000"},
        json={"email": f"{role}{school}@example.org", "password": "correct-horse-school-123"},
    )
    assert res.status_code == 200, res.text
    client.headers["Origin"] = "http://localhost:3000"


@pytest.fixture
def store(monkeypatch, tmp_path):
    from services.ingestion import library

    storage = LocalObjectStore(str(tmp_path / "objects"))
    monkeypatch.setattr(library, "object_store", lambda: storage)
    monkeypatch.setattr("services.ingestion.router.object_store", lambda: storage)
    return storage


def test_signature_and_filename():
    assert validate_file(PDF, "application/pdf") == "application/pdf"
    assert validate_file(b"<!doctype html><html>ok</html>") == "text/html"
    assert validate_file(b"hello lesson notes") == "text/plain"
    with pytest.raises(Exception):
        validate_file(b"\x7fELF\x00\x00", "application/pdf")
    with pytest.raises(Exception):
        validate_file(PDF, "image/png")
    with pytest.raises(Exception):
        safe_filename("../../run.exe", "application/pdf")


def test_upload_library_duplicate_download_and_event(client, accounts, db, store):
    signin(client)
    first = client.post(
        "/api/v1/resources/uploads",
        data={"license": "authorised-use"},
        files=[("files", ("chapter.pdf", PDF, "application/pdf"))],
    )
    assert first.status_code == 201, first.text
    record = first.json()["items"][0]
    assert record["duplicate"] is False
    second = client.post(
        "/api/v1/resources/uploads",
        data={"license": "authorised-use"},
        files=[("files", ("chapter.pdf", PDF, "application/pdf"))],
    )
    assert second.status_code == 201
    assert second.json()["items"][0]["duplicate"] is True
    rid = record["resource_id"]
    page = client.get("/api/v1/resources")
    assert page.status_code == 200 and page.json()["total"] == 1
    downloaded = client.get(f"/api/v1/resources/{rid}/download")
    assert downloaded.status_code == 200 and downloaded.content == PDF
    events = db.execute(select(ingestion_outbox)).mappings().all()
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["resource_id"] == rid
    assert payload["tenant_id"] == str(accounts[0][0].id)
    assert payload["object_key"] and payload["sha256"]
    assert payload["event_id"] == str(events[0]["id"])


def test_version_and_soft_delete(client, accounts, db, store):
    signin(client)
    first = client.post(
        "/api/v1/resources/uploads",
        data={"license": "permission"},
        files=[("files", ("one.txt", b"lesson one", "text/plain"))],
    )
    assert first.status_code == 201, first.text
    rid = first.json()["items"][0]["resource_id"]
    newer = client.post(
        "/api/v1/resources/uploads",
        data={"license": "permission", "resource_id": rid},
        files=[("files", ("two.txt", b"lesson two", "text/plain"))],
    )
    assert newer.status_code == 201
    details = client.get(f"/api/v1/resources/{rid}").json()
    assert [x["version"] for x in details["versions"]] == [2, 1]
    assert client.delete(f"/api/v1/resources/{rid}").status_code == 204
    assert client.get(f"/api/v1/resources/{rid}").status_code == 404


def test_auth_role_and_cross_tenant(client, accounts, store):
    assert client.get("/api/v1/resources").status_code == 401
    signin(client, "school_admin", 0)
    result = client.post(
        "/api/v1/resources/uploads",
        data={"license": "classroom"},
        files=[("files", ("test.pdf", PDF, "application/pdf"))],
    )
    assert result.status_code == 201
    rid = result.json()["items"][0]["resource_id"]
    signin(client, "school_admin", 1)
    assert client.get(f"/api/v1/resources/{rid}").status_code == 404
    assert client.delete(f"/api/v1/resources/{rid}").status_code == 404
    signin(client, "reviewer", 0)
    denied = client.post(
        "/api/v1/resources/uploads",
        data={"license": "classroom"},
        files=[("files", ("test.pdf", PDF, "application/pdf"))],
    )
    assert denied.status_code == 403


def test_malicious_upload_rejected(client, accounts, store):
    signin(client)
    bad = client.post(
        "/api/v1/resources/uploads",
        data={"license": "classroom"},
        files=[("files", ("payload.exe", b"\x7fELF\x00 malicious", "application/octet-stream"))],
    )
    assert bad.status_code == 422
    disguised = client.post(
        "/api/v1/resources/uploads",
        data={"license": "classroom"},
        files=[("files", ("course.jpg", PDF, "image/jpeg"))],
    )
    assert disguised.status_code == 422


def test_source_allowlist_and_ssrf(client, accounts, monkeypatch):
    signin(client)
    data = {
        "kind": "web",
        "source_uri": "https://school.example.edu/notes/",
        "license": "approved",
        "domains": ["school.example.edu"],
        "paths": ["/notes"],
    }
    source = client.post("/api/v1/sources", json=data)
    assert source.status_code == 201, source.text
    sid = source.json()["id"]
    denied = client.post(
        "/api/v1/imports/web", json={"source_id": sid, "url": "https://evil.example.com/"}
    )
    assert denied.status_code == 422
    localhost = client.post(
        "/api/v1/sources",
        json={**data, "source_uri": "http://127.0.0.1/", "domains": ["127.0.0.1"], "paths": ["/"]},
    )
    assert localhost.status_code == 422
    assert not allowed("https://school.example.edu/private/", {"school.example.edu"}, ["/notes"])
    assert (
        canonical("https://school.example.edu/notes/#fragment")
        == "https://school.example.edu/notes/"
    )
    with pytest.raises(ValueError):
        canonical("http://admin:secret@school.example.edu/")
    with pytest.raises(ValueError):
        safe_addresses("127.0.0.1", 80)


def test_telegram_webhook_deduplicates(client, accounts, db, monkeypatch):
    monkeypatch.setenv("SOMALOOM_TELEGRAM_BOT_TOKEN", "fake-test-token")
    monkeypatch.setenv("SOMALOOM_TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr("services.ingestion.router.enqueue", lambda *args: None)
    signin(client)
    source = client.post(
        "/api/v1/sources",
        json={
            "kind": "telegram",
            "chat_id": "-100100100",
            "source_uri": "telegram://-100100100",
            "license": "owner-approved",
        },
    )
    assert source.status_code == 201, source.text
    payload = {
        "update_id": 42,
        "channel_post": {
            "message_id": 7,
            "chat": {"id": -100100100},
            "document": {"file_id": "x", "file_unique_id": "a", "file_name": "notes.pdf"},
        },
    }
    url = "/api/v1/imports/telegram/webhook"
    assert client.post(url, json=payload).status_code == 403
    head = {"X-Telegram-Bot-Api-Secret-Token": "test-secret"}
    first = client.post(url, json=payload, headers=head)
    second = client.post(url, json=payload, headers=head)
    assert first.status_code == 200 and second.json()["duplicate"]
    receipts = db.execute(select(telegram_receipts)).mappings().all()
    assert len(receipts) == 1


def test_storage_tenant_path_safety(tmp_path):
    store = LocalObjectStore(str(tmp_path))
    a, b = uuid4(), uuid4()
    store.put(a, "originals/a", b"data")
    assert store.get(a, "originals/a") == b"data"
    with pytest.raises(FileNotFoundError):
        store.get(b, "originals/a")
    with pytest.raises(ValueError):
        store.path(a, "../../etc/passwd")

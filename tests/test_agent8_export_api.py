"""Publishing endpoint authorization smoke tests against Agent 1's fixtures."""

from uuid import uuid4

from conftest import sign_in


def test_publishing_routes_require_auth(client):
    assert client.get("/api/v1/documents").status_code == 401
    assert client.get("/api/v1/exports/" + str(uuid4()) + "/download").status_code == 401
    assert client.post("/api/v1/exports", json={}).status_code == 401


def test_cross_school_export_is_not_disclosed(client, accounts):
    assert sign_in(client, "teacher0@example.org").status_code == 200
    assert client.get("/api/v1/documents").json()["total"] == 0
    assert client.get("/api/v1/exports/" + str(uuid4()) + "/download").status_code == 404
    assert (
        client.post(
            "/api/v1/exports",
            headers={"Origin": "http://localhost:3000"},
            json={"document_version_id": str(uuid4()), "format": "pdf", "audience": "student"},
        ).status_code
        == 404
    )


def test_platform_admin_must_assume_school(client, accounts):
    assert sign_in(client).status_code == 200
    assert client.get("/api/v1/documents").status_code == 403

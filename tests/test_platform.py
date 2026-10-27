import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import fakeredis
import pytest
from app.core.models import AuthSession, BackgroundJob, User, resource_versions, resources, utcnow
from app.core.queue import ping_job
from app.core.storage import LocalObjectStore
from conftest import sign_in
from jsonschema import FormatChecker, validate
from rq import Queue, SimpleWorker
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from contracts.v1.schemas import Resource


def test_health_openapi_validation(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    spec = client.get("/api/v1/openapi.json")
    assert spec.status_code == 200
    assert "/api/v1/auth/login" in spec.json()["paths"]
    assert client.get("/api/v1/users/me").status_code == 401
    bad = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:3000"},
        json={"email": "bad", "password": "DO-NOT-REFLECT-ME"},
    )
    assert bad.status_code == 422
    assert "DO-NOT-REFLECT-ME" not in bad.text
    assert bad.json()["request_id"] == bad.headers["x-request-id"]
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "a@example.org", "password": "x"}
        ).status_code
        == 403
    )


def test_login_logout_expiry(client, db, accounts):
    assert sign_in(client).status_code == 200
    assert "httponly" in client.cookies.__str__().lower() or "somaloom_session" in client.cookies
    assert client.get("/api/v1/users/me").json()["role"] == "platform_admin"
    assert "password" not in client.get("/api/v1/users/me").text
    assert (
        client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert (
        client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:3000"}).status_code
        == 204
    )
    assert client.get("/api/v1/users/me").status_code == 401
    sign_in(client)
    session = db.scalar(select(AuthSession))
    session.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/v1/users/me").status_code == 401


def test_wrong_password_and_inactive(client, db, accounts):
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:3000"},
        json={"email": "admin@example.org", "password": "wrong"},
    )
    assert response.status_code == 401
    user = db.scalar(select(User).where(User.email == "admin@example.org"))
    user.active = False
    db.commit()
    assert sign_in(client).status_code == 401


def test_tenant_roles_and_provisioning(client, db, accounts):
    schools, _ = accounts
    assert sign_in(client, "teacher0@example.org").status_code == 200
    assert client.get("/api/v1/schools").json()["total"] == 1
    assert client.get(f"/api/v1/schools/{schools[1].id}").status_code == 404
    assert client.get("/api/v1/schools?page_size=101").status_code == 422
    assert (
        client.post(
            "/api/v1/organizations",
            headers={"Origin": "http://localhost:3000"},
            json={"name": "No"},
        ).status_code
        == 403
    )
    job = BackgroundJob(tenant_id=schools[1].id, kind="upload")
    own_job = BackgroundJob(
        tenant_id=schools[0].id, kind="generation", status="running", progress=25
    )
    db.add_all([job, own_job])
    db.commit()
    assert client.get(f"/api/v1/jobs/{job.id}").status_code == 404
    assert client.get(f"/api/v1/jobs/{own_job.id}").json()["progress"] == 25
    sign_in(client, "school_admin0@example.org")
    body = {
        "email": "new@example.org",
        "name": "New",
        "password": "long-password-123",
        "role": "teacher",
        "tenant_id": str(schools[1].id),
    }
    headers = {"Origin": "http://localhost:3000"}
    assert client.post("/api/v1/users", json=body, headers=headers).status_code == 403
    body["tenant_id"] = str(schools[0].id)
    assert client.post("/api/v1/users", json=body, headers=headers).status_code == 201
    assert client.post("/api/v1/users", json=body, headers=headers).status_code == 409
    body["role"] = "platform_admin"
    assert client.post("/api/v1/users", json=body, headers=headers).status_code == 403


def test_platform_organization_school_flow(client, accounts):
    sign_in(client)
    h = {"Origin": "http://localhost:3000"}
    org = client.post("/api/v1/organizations", headers=h, json={"name": "New org"})
    assert org.status_code == 201
    school = client.post(
        "/api/v1/schools",
        headers=h,
        json={"name": "New school", "organization_id": org.json()["id"]},
    )
    assert school.status_code == 201
    assert client.get("/api/v1/schools").json()["total"] == 3
    assert client.get("/api/v1/config").json()["runtime_ai_configured"] is False


def test_cross_tenant_foreign_key_rejected(db, accounts):
    schools, _ = accounts
    id = uuid4()
    db.execute(
        resources.insert().values(
            id=id, tenant_id=schools[0].id, title="Test", media_type="text/plain", provenance={}
        )
    )
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(
            resource_versions.insert().values(
                tenant_id=schools[1].id,
                resource_id=id,
                version=1,
                object_key="test",
                checksum_sha256="0" * 64,
                provenance={},
            )
        )
        db.commit()
    db.rollback()


def test_storage_tenant_paths_and_atomic_write(tmp_path):
    store = LocalObjectStore(str(tmp_path))
    a, b = uuid4(), uuid4()
    store.put(a, "v1/reference.txt", b"lesson")
    assert store.get(a, "v1/reference.txt") == b"lesson"
    with pytest.raises(FileExistsError):
        store.put(a, "v1/reference.txt", b"overwrite")
    assert store.get(a, "v1/reference.txt") == b"lesson"
    with pytest.raises(FileNotFoundError):
        store.get(b, "v1/reference.txt")
    for key in ("../escape", "/etc/passwd", "x/../../escape", "x\\escape"):
        with pytest.raises(ValueError):
            store.put(a, key, b"bad")
    (tmp_path / str(a) / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        store.put(a, "link/escape", b"bad")


def test_resource_contract_fixture():
    root = Path("contracts/v1")
    data = json.loads((root / "fixtures/resource.json").read_text())
    validate(
        data,
        json.loads((root / "Resource.schema.json").read_text()),
        format_checker=FormatChecker(),
    )
    assert Resource.model_validate(data).title.endswith("(MOCK)")


def test_queue_execution():
    connection = fakeredis.FakeRedis()
    queue = Queue("somaloom", connection=connection)
    job = queue.enqueue(ping_job)
    SimpleWorker([queue], connection=connection).work(burst=True)
    assert job.return_value() == "pong"


def test_readiness_unavailable_without_worker(client):
    result = client.get("/api/v1/ready")
    assert result.status_code == 503
    assert result.json()["database"] is True
    assert result.json()["worker"] is False


def test_mocks_disabled_in_test(client, accounts):
    sign_in(client)
    assert client.get("/api/v1/mocks/resource").status_code == 404


def test_login_rate_limit_and_secure_cookie(client, accounts, monkeypatch):
    from app.main import settings

    class RateRedis:
        def eval(self, *args):
            return 11

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr("app.main.redis_connection", lambda: RateRedis())
    result = sign_in(client)
    assert result.status_code == 429
    assert result.headers["retry-after"] == "60"

    class Available:
        def eval(self, *args):
            return 1

    monkeypatch.setattr("app.main.redis_connection", lambda: Available())
    result = sign_in(client)
    assert result.status_code == 200
    assert "Secure" in result.headers["set-cookie"]
    assert "HttpOnly" in result.headers["set-cookie"]
    assert "SameSite=lax" in result.headers["set-cookie"]


def test_rate_limit_fails_closed(client, monkeypatch):
    from app.main import settings

    monkeypatch.setattr(settings, "app_env", "production")

    def unavailable():
        raise ConnectionError()

    monkeypatch.setattr("app.main.redis_connection", unavailable)
    assert sign_in(client).status_code == 503


def test_all_contract_fixtures():
    from contracts.v1 import schemas

    for path in Path("contracts/v1/fixtures").glob("*.json"):
        name = "".join(word.title() for word in path.stem.split("_"))
        data = json.loads(path.read_text())
        getattr(schemas, name).model_validate(data)
        validate(
            data,
            json.loads(Path(f"contracts/v1/{name}.schema.json").read_text()),
            format_checker=FormatChecker(),
        )


def test_bearer_session_and_openapi_security(client, accounts):
    sign_in(client)
    token = client.cookies.get("somaloom_session")
    client.cookies.clear()
    result = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert result.status_code == 200
    spec = client.get("/api/v1/openapi.json").json()
    assert spec["paths"]["/api/v1/users/me"]["get"]["security"]
    assert (
        client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code
        == 204
    )
    assert (
        client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )


def test_all_development_mock_endpoints(client, accounts, monkeypatch):
    from app.main import settings

    assert sign_in(client, "teacher0@example.org").status_code == 200
    monkeypatch.setattr(settings, "app_env", "development")

    class Available:
        def eval(self, *args):
            return 1

    monkeypatch.setattr("app.main.redis_connection", lambda: Available())
    for path in Path("contracts/v1/fixtures").glob("*.json"):
        result = client.get(f"/api/v1/mocks/{path.stem}")
        assert result.status_code == 200, result.text
        assert result.json()["tenant_id"] == str(accounts[0][0].id)
    assert client.get("/api/v1/mocks/unknown").status_code == 422

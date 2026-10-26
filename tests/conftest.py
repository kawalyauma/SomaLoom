import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite://")
import fakeredis
import pytest
from app.auth.security import hasher
from app.core.database import get_db
from app.core.models import Base, Organization, School, User
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db():
    url = os.environ["DATABASE_URL"]
    engine = create_engine(
        url,
        **(
            {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
            if url == "sqlite://"
            else {}
        ),
    )
    if url == "sqlite://":
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def fk(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        yield session
        session.rollback()
    engine.dispose()


@pytest.fixture
def client(db, monkeypatch):
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    redis = fakeredis.FakeRedis()
    monkeypatch.setattr("app.core.router.redis_connection", lambda: redis)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def accounts(db):
    org = Organization(name="Test organization")
    db.add(org)
    db.flush()
    schools = [School(name=f"School {i}", organization_id=org.id) for i in range(2)]
    db.add_all(schools)
    db.flush()
    encoded = hasher.hash("correct-horse-school-123")
    users = [
        User(email="admin@example.org", name="Admin", role="platform_admin", password_hash=encoded)
    ]
    for i, school in enumerate(schools):
        for role in ("school_admin", "teacher", "reviewer"):
            users.append(
                User(
                    email=f"{role}{i}@example.org",
                    name=role,
                    role=role,
                    tenant_id=school.id,
                    password_hash=encoded,
                )
            )
    db.add_all(users)
    db.commit()
    return schools, users


def sign_in(client, email="admin@example.org"):
    return client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:3000"},
        json={"email": email, "password": "correct-horse-school-123"},
    )

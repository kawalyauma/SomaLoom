"""Database idempotency and tenant isolation against local SQLite; no live services."""

from __future__ import annotations

from uuid import uuid4

from app.core.models import Base, Organization, School, resource_versions, resources
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from services.extraction.jobs import create_extraction


def test_version_scoped_job_deduplication_and_tenant_isolation():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        org = Organization(name="Demo")
        db.add(org)
        db.flush()
        school1 = School(organization_id=org.id, name="Alpha")
        school2 = School(organization_id=org.id, name="Beta")
        db.add_all([school1, school2])
        db.flush()
        rid, vid = uuid4(), uuid4()
        db.execute(
            insert(resources).values(
                id=rid,
                tenant_id=school1.id,
                title="Lesson",
                media_type="text/html",
                provenance={"license": "CC-BY-4.0", "checksum_sha256": "a" * 64},
            )
        )
        db.execute(
            insert(resource_versions).values(
                id=vid,
                tenant_id=school1.id,
                resource_id=rid,
                version=1,
                object_key="resources/demo",
                checksum_sha256="a" * 64,
                provenance={"license": "CC-BY-4.0", "checksum_sha256": "a" * 64},
            )
        )
        db.commit()
        first = create_extraction(db, school1.id, vid)
        second = create_extraction(db, school1.id, vid)
        assert first == (second[0], second[1], True)
        # Third tuple field signals 'new'; repeated submission is existing.
        assert second[2] is False
        try:
            create_extraction(db, school2.id, vid)
        except LookupError:
            pass
        else:
            raise AssertionError("Cross-tenant extraction was not rejected")
    engine.dispose()

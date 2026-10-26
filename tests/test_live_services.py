import os

import pytest
from sqlalchemy import create_engine, text


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="PostgreSQL integration URL not supplied"
)
def test_pgvector_migration():
    with create_engine(os.environ["TEST_DATABASE_URL"]).connect() as db:
        assert db.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
        assert db.scalar(text("SELECT '[1,2,3]'::vector <-> '[1,2,3]'::vector")) == 0
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0001_foundation"


@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="Live Redis URL not supplied")
def test_live_redis_queue():
    from app.core.queue import ping_job
    from redis import Redis
    from rq import Queue, SimpleWorker

    connection = Redis.from_url(os.environ["TEST_REDIS_URL"])
    assert connection.ping()
    queue = Queue("somaloom-integration", connection=connection)
    job = queue.enqueue(ping_job)
    SimpleWorker([queue], connection=connection).work(burst=True)
    assert job.return_value() == "pong"

"""Periodic durable submission recovery for every integrated pipeline."""

import logging
import time
from datetime import timedelta

from app.core.database import SessionLocal
from app.core.models import BackgroundJob, utcnow
from app.core.queue import redis_connection
from sqlalchemy import select

from services.extraction.consumer import consume_once
from services.extraction.jobs import dispatch
from services.extraction.persistence import outbox
from services.generation.tasks import dispatch_queued
from services.ingestion.jobs import dispatch_pending, recover_queued
from services.knowledge.research import dispatch_pending as dispatch_knowledge


def cycle():
    from services.export.tasks import dispatch_queued as dispatch_exports

    dispatch_exports()
    dispatch_pending()
    recover_queued()
    consume_once()
    with SessionLocal() as db:
        # Timeouts exceed each bounded worker timeout. A killed worker must not
        # leave a job permanently running or silently restart billable inference.
        for job in db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.status == "running",
                BackgroundJob.updated_at < utcnow() - timedelta(minutes=70),
            )
        ):
            job.status, job.error, job.finished_at = "failed", "worker_timeout", utcnow()
        db.commit()
        pending = (
            db.execute(select(outbox).where(outbox.c.state == "pending").limit(100))
            .mappings()
            .all()
        )
        for row in pending:
            dispatch(row["job_id"])
            db.execute(
                outbox.update()
                .where(outbox.c.id == row["id"])
                .values(state="dispatched", attempts=row["attempts"] + 1)
            )
        db.commit()
        dispatch_knowledge(db)
    dispatch_queued()
    redis_connection().set("somaloom:dispatcher:heartbeat", utcnow().isoformat(), ex=45)


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            cycle()
        except Exception as exc:
            logging.warning("dispatcher_cycle_failed type=%s", type(exc).__name__)
        time.sleep(10)


if __name__ == "__main__":
    main()

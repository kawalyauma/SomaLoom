"""RQ entry point: only trusted job UUIDs in payload, never arbitrary code."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.models import BackgroundJob, generations
from app.core.queue import queue
from sqlalchemy import select

from services.ai.provider import ProviderError, configured_provider
from services.generation.orchestrator import create_draft
from services.generation.repository import (
    activity_event,
    finish,
    retrieve_evidence,
    save_draft,
    update_progress,
)
from services.generation.schema import GenerationInput

log = logging.getLogger("somaloom.generation")


class Cancelled(Exception):
    pass


def enqueue_generation(job_id: UUID) -> bool:
    """The durable GitHub bridge owns every creation request."""
    return True


def dispatch_queued(limit: int = 100) -> int:
    """DB queued jobs are the durable submission outbox; run periodically."""
    with SessionLocal() as db:
        ids = db.scalars(
            select(BackgroundJob.id)
            .where(
                BackgroundJob.kind == "generation",
                BackgroundJob.status == "queued",
            )
            .order_by(BackgroundJob.created_at)
            .limit(min(500, max(1, limit)))
        ).all()
    return sum(enqueue_generation(identifier) for identifier in ids)


async def _execute(job_id: UUID, tenant_id: UUID, generation_id: UUID, data: GenerationInput):
    async def progress(stage: str, amount: int):
        with SessionLocal() as db:
            if not update_progress(db, job_id, tenant_id, stage, amount):
                raise Cancelled()

    await progress("researching", 10)
    with SessionLocal() as db:
        actor_id = db.scalar(
            select(generations.c.requested_by).where(
                generations.c.id == generation_id, generations.c.tenant_id == tenant_id
            )
        )
        from services.generation.checkpoints import saved_bundle, save_bundle
        bundle = saved_bundle(db, tenant_id, generation_id)
        if bundle is None:
            bundle = retrieve_evidence(db, tenant_id, data, actor_id)
            save_bundle(db, tenant_id, generation_id, bundle)
    await progress("drafting", 35)
    settings = get_settings()
    if not settings.ai_provider or settings.ai_provider == "disabled":
        raise ProviderError("provider_unconfigured")
    from services.generation.families import generate_family

    from services.generation.checkpoints import CheckpointProvider
    provider = CheckpointProvider(configured_provider(settings.ai_provider), tenant_id, generation_id)
    model = os.environ.get("AI_MODEL", "gpt-5")
    title = body = draft = None
    if data.document_type.value in {
        "lesson_notes",
        "scheme_of_work",
        "lesson_plan",
        "teacher_guide",
        "exam",
        "test",
        "quiz",
        "assignment",
        "worksheet",
    }:
        with SessionLocal() as db:
            title, body = await generate_family(
                db, data, bundle, provider, model, tenant_id, generation_id
            )
    else:
        draft = await create_draft(data, bundle, provider, model=model, progress=progress)
    await progress("saving", 95)
    with SessionLocal() as db:
        # Recheck tenancy/status immediately before persistence.
        job = db.get(BackgroundJob, job_id, with_for_update=True)
        if not job or job.tenant_id != tenant_id or job.status != "running":
            raise Cancelled()
        if body is not None:
            from services.generation.repository import save_family

            save_family(db, tenant_id, generation_id, data.document_type.value, title, body)
        else:
            save_draft(db, tenant_id, generation_id, draft)
        # Atomic document+status transaction: avoid a published doc on cancellation.
        job.status = "succeeded"
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        values = db.execute(
            select(generations.c.parameters).where(
                generations.c.id == generation_id, generations.c.tenant_id == tenant_id
            )
        ).scalar_one()
        db.execute(
            generations.update()
            .where(generations.c.id == generation_id, generations.c.tenant_id == tenant_id)
            .values(
                parameters={
                    **activity_event(values, "awaiting_review", 100, "succeeded"),
                    "usage": {
                        "input_tokens": draft.metadata["input_tokens"] if draft else None,
                        "output_tokens": draft.metadata["output_tokens"] if draft else None,
                    },
                }
            )
        )
        db.commit()


def run_generation(job_id: str):
    """Redirect legacy queue entries into the GitHub bridge without inference."""
    with SessionLocal() as db:
        row=db.execute(select(generations).where(generations.c.job_id==UUID(job_id))).mappings().first()
        if not row:return
        values=dict(row['parameters']);values['execution_mode']='github'
        db.execute(generations.update().where(generations.c.id==row['id']).values(parameters=values));db.commit()

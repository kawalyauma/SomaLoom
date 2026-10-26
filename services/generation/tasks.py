"""RQ entry point: only trusted job UUIDs in payload, never arbitrary code."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.models import BackgroundJob, generations
from app.core.queue import queue
from services.ai.provider import ProviderError, configured_provider
from services.generation.orchestrator import create_draft
from services.generation.repository import (
    finish, retrieve_evidence, save_draft, update_progress,
)
from services.generation.schema import GenerationInput

log = logging.getLogger("somaloom.generation")


class Cancelled(Exception):
    pass


def enqueue_generation(job_id: UUID) -> bool:
    """Safe to repeat: RQ job ID deduplicates dispatch attempts."""
    try:
        queue().enqueue(
            "services.generation.tasks.run_generation",
            str(job_id), job_id="generation-" + str(job_id), job_timeout=700,
            result_ttl=86400, failure_ttl=86400,
        )
        return True
    except Exception:
        log.warning("generation_dispatch_unavailable job_id=%s", job_id)
        return False


def dispatch_queued(limit: int = 100) -> int:
    """DB queued jobs are the durable submission outbox; run periodically."""
    with SessionLocal() as db:
        ids = db.scalars(select(BackgroundJob.id).where(
            BackgroundJob.kind == "generation",
            BackgroundJob.status == "queued",
        ).order_by(BackgroundJob.created_at).limit(min(500, max(1, limit)))).all()
    return sum(enqueue_generation(identifier) for identifier in ids)


async def _execute(job_id: UUID, tenant_id: UUID, generation_id: UUID,
                   data: GenerationInput):
    async def progress(stage: str, amount: int):
        with SessionLocal() as db:
            if not update_progress(db, job_id, tenant_id, stage, amount):
                raise Cancelled()

    with SessionLocal() as db:
        bundle = retrieve_evidence(db, tenant_id, data)
    await progress("researching", 10)
    settings = get_settings()
    if not settings.ai_provider or settings.ai_provider == "disabled":
        raise ProviderError("provider_unconfigured")
    draft = await create_draft(
        data, bundle, configured_provider(settings.ai_provider),
        model=os.environ.get("AI_MODEL", "gpt-5"),
        progress=progress,
    )
    await progress("saving", 95)
    with SessionLocal() as db:
        # Recheck tenancy/status immediately before persistence.
        job = db.get(BackgroundJob, job_id)
        if not job or job.tenant_id != tenant_id or job.status != "running":
            raise Cancelled()
        save_draft(db, tenant_id, generation_id, draft)
        # Atomic document+status transaction: avoid a published doc on cancellation.
        job.status = "succeeded"
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        values = db.execute(select(generations.c.parameters).where(
            generations.c.id == generation_id,
            generations.c.tenant_id == tenant_id)).scalar_one()
        db.execute(generations.update().where(
            generations.c.id == generation_id, generations.c.tenant_id == tenant_id
        ).values(parameters={**values, "stage": "awaiting_review",
                             "usage": {"input_tokens": draft.metadata["input_tokens"],
                                       "output_tokens": draft.metadata["output_tokens"]}}))
        db.commit()


def run_generation(job_id: str):
    try:
        identifier = UUID(job_id)
    except (ValueError, TypeError):
        return
    with SessionLocal() as db:
        job = db.get(BackgroundJob, identifier)
        if not job or job.kind != "generation" or job.status in (
            "cancelled", "failed", "succeeded"
        ):
            return
        # Running jobs are not restarted by a duplicate dispatcher.
        if job.status != "queued":
            return
        row = db.execute(select(generations).where(
            generations.c.job_id == identifier,
            generations.c.tenant_id == job.tenant_id
        )).mappings().first()
        if row is None:
            finish(db, identifier, job.tenant_id, "failed", "generation_record_missing")
            return
        tenant_id = job.tenant_id
        generation_id = row["id"]
        try:
            data = GenerationInput.model_validate(row["parameters"]["request"])
        except Exception:
            finish(db, identifier, tenant_id, "failed", "invalid_generation_request")
            return
    try:
        with SessionLocal() as db:
            if not update_progress(db, identifier, tenant_id, "starting", 1):
                return
        asyncio.run(_execute(identifier, tenant_id, generation_id, data))
    except Cancelled:
        log.info("generation_cancelled job_id=%s", identifier)
    except ProviderError as error:
        with SessionLocal() as db:
            finish(db, identifier, tenant_id, "failed", error.code)
        log.warning("generation_provider_failed job_id=%s code=%s", identifier, error.code)
    except ValueError as error:
        known = {"topic_outcome_mapping_missing", "invalid_resource_filter"}
        code = str(error) if str(error) in known else "generation_validation_failed"
        with SessionLocal() as db:
            finish(db, identifier, tenant_id, "failed", code)
        log.warning("generation_validation_failed job_id=%s code=%s", identifier, code)
    except Exception:
        with SessionLocal() as db:
            finish(db, identifier, tenant_id, "failed", "generation_internal_error")
        log.exception("generation_internal_failure job_id=%s", identifier)

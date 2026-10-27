"""Durable queue intent and resource-event receipts, in the source transaction."""

from app.core.models import col, domain
from sqlalchemy import Integer, String, UniqueConstraint

outbox = domain(
    "extraction_outbox",
    [col("state", String(20)), col("attempts", Integer)],
    [("extraction_id", "extractions"), ("job_id", "background_jobs")],
)
outbox.append_constraint(
    UniqueConstraint("tenant_id", "extraction_id", name="uq_extraction_dispatch")
)
receipts = domain(
    "extraction_event_receipts",
    [],
    [("version_id", "resource_versions"), ("job_id", "background_jobs")],
)

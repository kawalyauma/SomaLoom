"""Agent 2 feature tables; Agent 1 must apply the reviewed migration proposal."""

from app.core.models import col, domain
from sqlalchemy import JSON, Integer, String, Text, UniqueConstraint

import_runs = domain(
    "ingestion_runs",
    [
        col("kind", String(20)),
        col("status", String(20)),
        col("checkpoint", JSON),
        col("report", JSON),
        col("error", Text, True),
    ],
    [("source_id", "import_sources"), ("job_id", "background_jobs")],
)
ingestion_outbox = domain(
    "ingestion_outbox",
    [
        col("event_type", String(80)),
        col("payload", JSON),
        col("state", String(20)),
        col("attempts", Integer),
        col("last_error", Text, True),
    ],
    [("version_id", "resource_versions"), ("job_id", "background_jobs")],
)
ingestion_outbox.append_constraint(UniqueConstraint("version_id", "event_type"))
telegram_receipts = domain(
    "telegram_receipts",
    [
        col("chat_id", String(80)),
        col("message_id", String(80)),
        col("file_unique_id", String(200), True),
        col("payload", JSON),
        col("state", String(20)),
    ],
    [("source_id", "import_sources"), ("job_id", "background_jobs")],
)
telegram_receipts.append_constraint(UniqueConstraint("tenant_id", "chat_id", "message_id"))

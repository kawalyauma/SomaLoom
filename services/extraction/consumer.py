"""Consume the actual ingestion Redis Stream; ACK only durable extraction intent."""

import json
import logging
import socket

from app.core.queue import redis_connection
from redis.exceptions import ResponseError

from services.extraction.jobs import accept_resource_available

STREAM = "somaloom:resource.available"
GROUP = "somaloom-extraction-v1"
log = logging.getLogger(__name__)


def consume_once(connection=None):
    connection = connection or redis_connection()
    try:
        connection.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    consumer = socket.gethostname()
    claimed = connection.xautoclaim(STREAM, GROUP, consumer, 60000, "0-0", count=20)
    entries = claimed[1]
    for _stream, messages in connection.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=20):
        entries.extend(messages)
    for stream_id, fields in entries:
        try:
            event = json.loads(fields.get(b"payload", fields.get("payload", "{}")))
            accept_resource_available(event)
            connection.xack(STREAM, GROUP, stream_id)
        except Exception as exc:
            # Retain pending entry for retry; log no source payload or credentials.
            log.warning("resource_event_pending id=%s error=%s", stream_id, type(exc).__name__)
    return len(entries)

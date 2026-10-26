"""RQ tasks and durable outbox delivery. Jobs resolve tenant ownership from the DB."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.models import BackgroundJob, sources
from app.core.queue import queue, redis_connection
from app.core.models import utcnow
from services.ingestion.crawler import crawl
from services.ingestion.library import MAX_BYTES, publish_version, validate_file
from services.ingestion.models import import_runs, ingestion_outbox, telegram_receipts

def enqueue(kind: str, item_id: UUID):
    queue().enqueue(
        f"services.ingestion.jobs.{kind}", str(item_id),
        job_id=f"ingestion-{kind}-{item_id}-{uuid4()}",
        job_timeout=1800 if kind == "process_web" else 300,
        result_ttl=600,
    )

def transition(db, job_id, status, progress=None, error=None):
    job = db.get(BackgroundJob, job_id)
    if not job:
        raise ValueError("Missing job")
    if job.status in {"cancelled", "succeeded"}:
        return False
    if status == "running" and job.status == "running":
        return False
    job.status = status
    if progress is not None:
        job.progress = min(100, max(0, progress))
    job.error = error
    if status in {"succeeded", "failed", "cancelled"}:
        job.finished_at = utcnow()
    db.commit()
    return True

def dispatch_pending(limit=20):
    """Run periodically in a separate ingestion dispatcher; safe to retry on crashes."""
    submitted = 0
    with SessionLocal() as db:
        rows = db.execute(select(ingestion_outbox).where(
            (ingestion_outbox.c.state == "pending") |
            ((ingestion_outbox.c.state == "enqueued") &
             (ingestion_outbox.c.updated_at < utcnow() - timedelta(minutes=10)))
        ).order_by(ingestion_outbox.c.created_at).limit(limit)).mappings().all()
        for row in rows:
            event_id = row["id"]
            # Optimistically claimed; re-queued after TTL if worker/Redis is unavailable.
            result = db.execute(ingestion_outbox.update().where(
                ingestion_outbox.c.id == event_id,
                ingestion_outbox.c.tenant_id == row["tenant_id"],
                ingestion_outbox.c.state == row["state"],
            ).values(state="enqueued", attempts=row["attempts"] + 1))
            if result.rowcount != 1:
                db.rollback()
                continue
            db.commit()
            try:
                enqueue("deliver_outbox", event_id)
                submitted += 1
            except Exception:
                db.execute(ingestion_outbox.update().where(
                    ingestion_outbox.c.id == event_id
                ).values(state="pending", last_error="Queue unavailable"))
                db.commit()
    return submitted

def deliver_outbox(event_id: str):
    """At-least-once delivery to Redis Stream; Agent 3 deduplicates event_id."""
    with SessionLocal() as db:
        row = db.execute(select(ingestion_outbox).where(
            ingestion_outbox.c.id == UUID(event_id))).mappings().first()
        if not row or row["state"] == "delivered":
            return "already-delivered"
        job = db.get(BackgroundJob, row["job_id"])
        if not job or job.tenant_id != row["tenant_id"] or job.status == "cancelled":
            return "cancelled"
        try:
            redis_connection().xadd(
                "somaloom:resource.available",
                {"event_id": event_id, "payload": json.dumps(row["payload"])},
                maxlen=100000, approximate=True,
            )
            db.execute(ingestion_outbox.update().where(
                ingestion_outbox.c.id == row["id"]
            ).values(state="delivered", last_error=None))
            transition(db, row["job_id"], "succeeded", 100)
        except Exception:
            db.rollback()
            db.execute(ingestion_outbox.update().where(
                ingestion_outbox.c.id == row["id"]
            ).values(state="pending", last_error="Delivery unavailable"))
            db.commit()
            transition(db, row["job_id"], "failed", error="Delivery unavailable")
            raise
    return "delivered"

class ImportCancelled(Exception):
    pass

def process_web(run_id: str):
    run_id = UUID(run_id)
    with SessionLocal() as db:
        run = db.execute(select(import_runs).where(import_runs.c.id == run_id)).mappings().first()
        if not run:
            return "missing"
        tenant, source_id, job_id = run["tenant_id"], run["source_id"], run["job_id"]
        src = db.execute(select(sources).where(
            sources.c.id == source_id, sources.c.tenant_id == tenant)).mappings().first()
        if not src or src["kind"] != "web" or not src["config"].get("active", True):
            transition(db, job_id, "failed", error="Source disconnected")
            return "source-disabled"
        if not transition(db, job_id, "running", 1):
            return "cancelled"
        db.execute(import_runs.update().where(import_runs.c.id == run_id).values(status="running"))
        db.commit()
        config = src["config"]
        opts = run["checkpoint"]
        try:
            count = 0
            def save(state):
                current_status = db.scalar(select(BackgroundJob.status).where(
                    BackgroundJob.id == job_id, BackgroundJob.tenant_id == tenant))
                if current_status == "cancelled":
                    raise ImportCancelled()
                db.execute(import_runs.update().where(
                    import_runs.c.id == run_id, import_runs.c.tenant_id == tenant
                ).values(checkpoint={**opts, "crawl": state}, report=state["reports"]))
                db.commit()
            for url, body, content_type in crawl(
                opts["url"], domains=set(config["domains"]), paths=config.get("paths", ["/"]),
                max_pages=opts["max_pages"], max_depth=opts.get("max_depth", 2),
                delay=max(0.5, opts.get("delay", 1)), checkpoint=opts.get("crawl"),
                save=save, dry_run=opts.get("dry_run", False),
            ):
                status = db.scalar(select(BackgroundJob.status).where(
                    BackgroundJob.id == job_id, BackgroundJob.tenant_id == tenant))
                if status == "cancelled":
                    db.execute(import_runs.update().where(import_runs.c.id == run_id).values(status="cancelled"))
                    db.commit()
                    return "cancelled"
                mime = validate_file(body, content_type)
                publish_version(
                    db, tenant, None, body, mime, url.split("/")[-1] or "page.txt",
                    __import__("hashlib").sha256(body).hexdigest(), url[:500], src["license"],
                    url, "web", source_id,
                )
                count += 1
            db.execute(import_runs.update().where(import_runs.c.id == run_id).values(status="succeeded"))
            transition(db, job_id, "succeeded", 100)
            return f"imported={count}"
        except ImportCancelled:
            db.rollback()
            db.execute(import_runs.update().where(import_runs.c.id == run_id).values(
                status="cancelled"
            ))
            db.commit()
            return "cancelled"
        except Exception:
            db.rollback()
            db.execute(import_runs.update().where(
                import_runs.c.id == run_id).values(status="failed", error="Import failed"))
            transition(db, job_id, "failed", error="Import failed")
            raise

def telegram_api(method: str, params: dict):
    """Only official Telegram host; never persist tokens or raw URL."""
    token = os.getenv("SOMALOOM_TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Telegram bot token not configured")
    url = "https://api.telegram.org/bot" + token + "/" + method
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                reply = json.loads(response.read(1024 * 1024))
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                try:
                    wait = min(30, max(1, int(exc.headers.get("Retry-After", "2"))))
                except (TypeError, ValueError):
                    wait = 2
                time.sleep(wait)
                continue
            raise RuntimeError(f"Telegram API HTTP {exc.code}") from None
        except urllib.error.URLError:
            raise RuntimeError("Telegram API connection unavailable") from None
    if not reply.get("ok"):
        raise RuntimeError("Telegram API rejected request")
    return reply["result"]

def telegram_download(file_id: str):
    meta = telegram_api("getFile", {"file_id": file_id})
    path = meta.get("file_path", "")
    if not path or path.startswith("/") or ".." in path.split("/") or "\\" in path:
        raise ValueError("Invalid Telegram file path")
    if int(meta.get("file_size", 0)) > MAX_BYTES:
        raise ValueError("Telegram file exceeds size cap")
    token = os.environ["SOMALOOM_TELEGRAM_BOT_TOKEN"]
    url = "https://api.telegram.org/file/bot" + token + "/" + urllib.parse.quote(path, safe="/")
    # Official Bot API file endpoint. Deny redirects so the token never leaks to another host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(url, timeout=30) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram download HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("Telegram download unavailable") from None
    if len(body) > MAX_BYTES:
        raise ValueError("Telegram file exceeds size cap")
    return body

def process_telegram(receipt_id: str):
    with SessionLocal() as db:
        row = db.execute(select(telegram_receipts).where(
            telegram_receipts.c.id == UUID(receipt_id))).mappings().first()
        if not row:
            return "missing"
        tenant, source_id, job_id = row["tenant_id"], row["source_id"], row["job_id"]
        source = db.execute(select(sources).where(
            sources.c.id == source_id, sources.c.tenant_id == tenant)).mappings().first()
        if not source or not source["config"].get("active", False):
            transition(db, job_id, "failed", error="Source disconnected")
            return "disconnected"
        if not transition(db, job_id, "running", 1):
            return "cancelled"
        try:
            payload = row["payload"]
            data = telegram_download(payload["file_id"])
            mime = validate_file(data)  # Telegram MIME is untrusted.
            from services.ingestion.library import safe_filename
            name = safe_filename(payload.get("filename"), mime)
            sha = __import__("hashlib").sha256(data).hexdigest()
            provenance_url = f"telegram://{row['chat_id']}/{row['message_id']}"
            publish_version(
                db, tenant, None, data, mime, name, sha, name, source["license"],
                provenance_url, "telegram", source_id,
            )
            db.execute(telegram_receipts.update().where(
                telegram_receipts.c.id == row["id"]).values(state="succeeded"))
            transition(db, job_id, "succeeded", 100)
            return "imported"
        except Exception:
            db.rollback()
            db.execute(telegram_receipts.update().where(
                telegram_receipts.c.id == row["id"]).values(state="failed"))
            transition(db, job_id, "failed", error="Telegram import failed")
            raise

def recover_queued(limit=25):
    """Re-submit persisted unstarted imports after a failed queue submission."""
    with SessionLocal() as db:
        stale = utcnow() - timedelta(minutes=10)
        runs = db.execute(select(import_runs).where(
            (import_runs.c.status == "queued") |
            ((import_runs.c.status == "scheduled") & (import_runs.c.updated_at < stale))
        ).limit(limit)).mappings().all()
        receipts = db.execute(select(telegram_receipts).where(
            (telegram_receipts.c.state == "queued") |
            ((telegram_receipts.c.state == "scheduled") & (telegram_receipts.c.updated_at < stale))
        ).limit(limit)).mappings().all()
        for table, kind, rows in ((import_runs, "process_web", runs),
                                  (telegram_receipts, "process_telegram", receipts)):
            for row in rows:
                try:
                    enqueue(kind, row["id"])
                    if table is import_runs:
                        db.execute(table.update().where(
                            table.c.id == row["id"], table.c.status == row["status"]
                        ).values(status="scheduled"))
                    else:
                        db.execute(table.update().where(
                            table.c.id == row["id"], table.c.state == row["state"]
                        ).values(state="scheduled"))
                    db.commit()
                except Exception:
                    db.rollback()
    return len(runs) + len(receipts)

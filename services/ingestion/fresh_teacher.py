"""Poll explicitly connected Fresh-Teacher GitHub repositories into the school library."""
import concurrent.futures
import hashlib
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.models import resources, sources
from services.ingestion.library import MAX_BYTES, publish_version, safe_filename, validate_file

ORG = "Fresh-Teacher"
# The library currently validates and extracts PDFs and DOCX. Legacy .doc files
# are ignored until a safe, tested binary Word extractor is installed.
SUPPORTED = {".pdf", ".docx"}
USER_AGENT = "SomaLoom-FreshTeacher-Importer/1.0"


def github_json(url):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("github_response_limit")
    return json.loads(raw)


def source_uri(repo, path, blob_sha):
    return f"https://github.com/{ORG}/{repo}/blob/{blob_sha}/{urllib.parse.quote(path, safe='/')}"


def already_imported(tenant_id, uri):
    with SessionLocal() as db:
        return bool(db.scalar(select(resources.c.id).where(resources.c.tenant_id == tenant_id, resources.c.provenance["source_uri"].as_string() == uri).limit(1)))


def fetch(item):
    url = f"https://raw.githubusercontent.com/{ORG}/{urllib.parse.quote(item['repo'], safe='')}/{item['commit']}/{urllib.parse.quote(item['path'], safe='/')}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    data = bytearray()
    with urllib.request.urlopen(request, timeout=90) as response:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            if len(data) + len(chunk) > MAX_BYTES:
                raise ValueError("resource_size_limit")
            data.extend(chunk)
            digest.update(chunk)
    if len(data) != item["size"]:
        raise ValueError("resource_size_mismatch")
    payload=bytes(data)
    git_sha=hashlib.sha1(b"blob "+str(len(payload)).encode()+b"\0"+payload).hexdigest()
    if git_sha!=item["blob_sha"]:
        raise ValueError("github_blob_checksum_mismatch")
    return payload,digest.hexdigest()


def import_one(source, item, license_name):
    data, checksum = fetch(item)
    mime = validate_file(data)
    filename = safe_filename(PurePosixPath(item["path"]).name, mime)
    uri = source_uri(item["repo"], item["path"], item["blob_sha"])
    with SessionLocal() as db:
        latest = db.execute(select(sources).where(sources.c.id == source["id"], sources.c.tenant_id == source["tenant_id"])).mappings().first()
        if not latest or not latest["config"].get("active", True):
            return "disconnected"
        result = publish_version(db, UUID(str(source["tenant_id"])), None, data, mime, filename, checksum, PurePosixPath(filename).stem, license_name, uri, "web", UUID(str(source["id"])))
    return "duplicate" if result.get("duplicate") else "imported"


def update_source(source_id, tenant_id, config, license=None):
    with SessionLocal() as db:
        values = {"config": config}
        if license is not None:
            values["license"] = license
        db.execute(sources.update().where(sources.c.id == source_id, sources.c.tenant_id == tenant_id, sources.c.kind == "fresh_teacher").values(**values))
        db.commit()


def scan_source(source):
    config = dict(source["config"] or {})
    now = time.time()
    if not config.get("active", True) or now - float(config.get("last_scan_epoch", 0)) < 3600:
        return
    config.update(status="scanning", error=None)
    update_source(source["id"], source["tenant_id"], config)
    try:
        match = re.fullmatch(r"https://github\.com/Fresh-Teacher/([A-Za-z0-9_.-]{1,100})", source["source_uri"], re.IGNORECASE)
        if not match:
            raise ValueError("invalid_repository_url")
        repo = match.group(1)
        api_repo = urllib.parse.quote(repo, safe="")
        metadata = github_json(f"https://api.github.com/repos/{ORG}/{api_repo}")
        branch = metadata.get("default_branch") or "main"
        license_id = ((metadata.get("license") or {}).get("spdx_id") or "unknown").strip()
        allowed_license = license_id.lower() not in {"", "unknown", "none", "noassertion"}
        if config.get("download_mode", "licensed_downloads") == "licensed_downloads" and not allowed_license:
            config.update(status="skipped_unlicensed", detected_license=license_id, last_checked=datetime.now(timezone.utc).isoformat(), last_scan_epoch=now)
            update_source(source["id"], source["tenant_id"], config)
            return
        commit_obj = github_json(f"https://api.github.com/repos/{ORG}/{api_repo}/commits/{urllib.parse.quote(branch, safe='')}")
        commit = commit_obj["sha"]
        tree_sha = commit_obj["commit"]["tree"]["sha"]
        tree = github_json(f"https://api.github.com/repos/{ORG}/{api_repo}/git/trees/{tree_sha}?recursive=1")
        if tree.get("truncated"):
            raise ValueError("github_tree_truncated")
        candidates = []
        for entry in tree.get("tree", []):
            path = entry.get("path", "")
            if entry.get("type") != "blob" or PurePosixPath(path).suffix.lower() not in SUPPORTED:
                continue
            try:
                size = int(entry.get("size") or 0)
            except (TypeError, ValueError):
                continue
            if size < 1 or size > MAX_BYTES:
                continue
            uri = source_uri(repo, path, entry["sha"])
            if not already_imported(source["tenant_id"], uri):
                candidates.append({"repo": repo, "path": path, "blob_sha": entry["sha"], "commit": commit, "size": size})
        imported = duplicates = failures = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="fresh-teacher") as pool:
            pending = {pool.submit(import_one, source, item, license_id if allowed_license else "unknown"): item for item in candidates[:1000]}
            for future in concurrent.futures.as_completed(pending):
                try:
                    result = future.result()
                    imported += result == "imported"
                    duplicates += result == "duplicate"
                except HTTPException:
                    failures += 1
                except Exception as exc:
                    failures += 1
                    logging.warning("fresh_teacher_item_retry type=%s", type(exc).__name__)
        config.update(status="watching", detected_license=license_id, last_commit=commit, last_checked=datetime.now(timezone.utc).isoformat(), last_scan_epoch=now, error=None, discovered=len(candidates), imported_this_scan=imported, duplicates_this_scan=duplicates, failed_this_scan=failures)
        update_source(source["id"], source["tenant_id"], config, license=license_id if allowed_license else "unknown")
    except Exception as exc:
        config.update(status="retrying", error="Repository scan will retry automatically (" + type(exc).__name__ + ")", last_scan_epoch=now)
        update_source(source["id"], source["tenant_id"], config)
        logging.warning("fresh_teacher_repository_retry type=%s", type(exc).__name__)


def cycle():
    with SessionLocal() as db:
        connected = db.execute(select(sources).where(sources.c.kind == "fresh_teacher")).mappings().all()
    for source in connected:
        scan_source(dict(source))

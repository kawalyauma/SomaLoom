"""somaloom-import CLI (python -m services.ingestion.cli web ...)."""
import argparse
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import UUID

from services.ingestion.crawler import canonical, crawl
from services.ingestion.library import MAX_BYTES

def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)

def api_upload(api_url, token, source_id, url, body, mime, license):
    if len(body) > MAX_BYTES:
        raise ValueError("File exceeds limit")
    parsed = urllib.parse.urlsplit(api_url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")
    ):
        raise ValueError("API endpoint must be HTTPS or local development")
    if not token or not source_id:
        raise ValueError("API token and source ID are required for live imports")
    boundary = "somaloomimport" + os.urandom(12).hex()
    filename = "document.pdf" if mime == "application/pdf" else "page.txt"
    parts = [
        ("license", license.encode()),
        ("source_uri", url.encode()),
        ("source_id", str(UUID(source_id)).encode()),
    ]
    chunks = []
    for key, value in parts:
        chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n").encode() + value + b"\r\n")
    chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n").encode() + body + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        api_url.rstrip("/") + "/api/v1/resources/uploads", data=b"".join(chunks),
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(req, timeout=60) as reply:
        return json.loads(reply.read(200_000))

def main(argv=None):
    parser = argparse.ArgumentParser(prog="somaloom-import")
    sub = parser.add_subparsers(dest="command", required=True)
    web = sub.add_parser("web", help="Crawl only explicitly authorized websites")
    web.add_argument("--url", required=True)
    web.add_argument("--allow-domain", action="append", required=True,
                     help="Exactly authorized hostname; repeat to allow more")
    web.add_argument("--allow-path", action="append", default=[])
    web.add_argument("--max-pages", type=int, default=100)
    web.add_argument("--max-depth", type=int, default=2)
    web.add_argument("--delay", type=float, default=1.0)
    web.add_argument("--dry-run", action="store_true")
    web.add_argument("--authorized", action="store_true", help="Confirm express authorization")
    web.add_argument("--checkpoint", default=".somaloom-web-checkpoint.json")
    web.add_argument("--report", default="somaloom-import-report.json")
    web.add_argument("--api-url", default=os.getenv("SOMALOOM_API_URL", "http://localhost:8000"))
    web.add_argument("--token", default=os.getenv("SOMALOOM_API_TOKEN"))
    web.add_argument("--source-id", default=os.getenv("SOMALOOM_SOURCE_ID"))
    web.add_argument("--license", default="operator-authorized")
    args = parser.parse_args(argv)
    if args.command == "web":
        if not args.dry_run and not args.authorized:
            parser.error("Live import requires --authorized (owned or expressly permitted content)")
        if not args.dry_run and (not args.source_id or not args.token):
            parser.error("Live import requires SOMALOOM_SOURCE_ID and SOMALOOM_API_TOKEN")
        resume = None
        if Path(args.checkpoint).exists():
            resume = json.loads(Path(args.checkpoint).read_text())
            if resume.get("seed") != canonical(args.url):
                parser.error("Checkpoint belongs to another crawl")
            resume = resume.get("state")
        report = {"seed": canonical(args.url), "documents": [], "errors": []}
        def persist(state):
            save_json(args.checkpoint, {"seed": canonical(args.url), "state": state})
            report["crawl"] = state["reports"]
            save_json(args.report, report)
        try:
            for url, body, mime in crawl(
                args.url, domains=set(d.lower() for d in args.allow_domain),
                paths=args.allow_path or ["/"], max_pages=args.max_pages,
                max_depth=args.max_depth, delay=args.delay, dry_run=args.dry_run,
                checkpoint=resume, save=persist,
            ):
                try:
                    result = api_upload(args.api_url, args.token, args.source_id,
                                        url, body, mime, args.license)
                    report["documents"].append({"url": url, "result": result})
                except (ValueError, urllib.error.URLError) as err:
                    report["errors"].append({"url": url, "error": type(err).__name__})
                save_json(args.report, report)
        except (ValueError, OSError) as err:
            report["errors"].append({"error": str(err)})
            save_json(args.report, report)
            print(f"Import stopped: {err}", file=sys.stderr)
            return 1
        save_json(args.report, report)
        print(json.dumps({"report": args.report, "documents": len(report["documents"]),
                          "errors": len(report["errors"])}))
        return 0 if not report["errors"] else 1
    return 2

if __name__ == "__main__":
    raise SystemExit(main())

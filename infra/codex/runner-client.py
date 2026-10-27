#!/usr/bin/env python3
"""Exec-compatible client for the separately isolated inference container."""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://codex-inference:8090"
TOKEN_FILE = Path("/run/secrets/codex-runner-token")


def request(path, data=None):
    headers = {"Authorization": "Bearer " + TOKEN_FILE.read_text().strip()}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, json.dumps(data).encode() if data is not None else None, headers)
    with urllib.request.urlopen(req, timeout=115) as response:
        raw = response.read(1100000)
        if len(raw) > 1090000:
            raise ValueError("response_limit")
        return json.loads(raw)


def main():
    if sys.argv[1:] == ["exec", "--help"]:
        print(request("/help")["help"])
        return
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["exec"])
    p.add_argument("--skip-git-repo-check", action="store_true")
    p.add_argument("--sandbox", choices=["read-only"], required=True)
    p.add_argument("--output-schema", required=True)
    p.add_argument("--output-last-message", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("input", choices=["-"])
    args = p.parse_args()
    prompt = sys.stdin.buffer.read(220001)
    if len(prompt) > 220000:
        raise ValueError("input_limit")
    schema = Path(args.output_schema)
    if schema.stat().st_size > 70000:
        raise ValueError("schema_limit")
    result = request("/generate", {"prompt": prompt.decode(), "schema": json.loads(schema.read_text()), "model": args.model})
    Path(args.output_last_message).write_text(json.dumps(result["answer"]))
    print(result.get("events", ""))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        if error.code == 429:
            print("provider_busy", file=sys.stderr)
            sys.exit(75)
        try:
            code = json.loads(error.read(1024)).get("error", "provider_unreachable")
        except Exception:
            code = "provider_unreachable"
        print(code, file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("provider_unreachable", file=sys.stderr)
        sys.exit(1)

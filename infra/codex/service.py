"""Bounded, tool-free Codex inference. No application credentials or host access."""
import hmac
import json
import os
import signal
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BIN = "/opt/codex-bin/codex"
TOKEN = Path("/run/secrets/codex-runner-token").read_text().strip()
LOCK = threading.BoundedSemaphore(1)
MODEL = "gpt-6.1-sol"


def strict_schema(value):
    if isinstance(value, list):
        return [strict_schema(x) for x in value]
    if not isinstance(value, dict):
        return value
    result = {k: strict_schema(v) for k, v in value.items() if k != "default"}
    if "properties" in result:
        result["additionalProperties"] = False
        result["required"] = list(result["properties"])
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # No prompts, credentials or response bodies in logs.

    def reply(self, status, value):
        encoded = json.dumps(value).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authenticated(self):
        return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + TOKEN)

    def do_GET(self):
        if self.path == "/healthz":
            return self.reply(200, {"ok": True, "version": "0.164.0"})
        if not self.authenticated():
            return self.reply(401, {"error": "unauthorized"})
        if self.path != "/help":
            return self.reply(404, {"error": "not_found"})
        r = subprocess.run([BIN, "exec", "--help"], capture_output=True, timeout=8)
        return self.reply(200, {"help": r.stdout.decode(), "version": "0.164.0"})

    def do_POST(self):
        if not self.authenticated():
            return self.reply(401, {"error": "unauthorized"})
        if self.path != "/generate":
            return self.reply(404, {"error": "not_found"})
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 300000:
            return self.reply(413, {"error": "input_limit"})
        try:
            data = json.loads(self.rfile.read(length))
            prompt, schema = data["prompt"], data["schema"]
            if not isinstance(prompt, str) or len(prompt.encode()) > 220000 or not isinstance(schema, dict):
                raise ValueError
            if data.get("model") != MODEL:
                return self.reply(400, {"error": "unsupported_model"})
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {"error": "invalid_request"})
        if not LOCK.acquire(blocking=False):
            return self.reply(429, {"error": "busy"})
        proc = None
        try:
            with tempfile.TemporaryDirectory(prefix="inference-") as directory:
                schema_path = Path(directory) / "schema.json"
                answer_path = Path(directory) / "answer.json"
                schema_path.write_text(json.dumps(strict_schema(schema)))
                argv = [BIN, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
                        "--disable", "shell_tool", "--disable", "code_mode_host",
                        "--disable", "code_mode", "--disable", "sleep_tool",
                        "--skip-git-repo-check", "--sandbox", "read-only", "--json",
                        "--output-schema", str(schema_path), "--output-last-message", str(answer_path),
                        "--model", MODEL, "-"]
                env = {k: os.environ[k] for k in ["HOME", "CODEX_HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"] if k in os.environ}
                env.update({"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"})
                proc = subprocess.Popen(argv, cwd=directory, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                stdout, stderr = proc.communicate(prompt.encode(), timeout=110)
                if proc.returncode:
                    reason = stderr.decode("utf8", "replace").lower()
                    error = "provider_auth_expired" if any(x in reason for x in ["unauthorized", "token expired", "login"]) else "provider_execution_failed"
                    print(json.dumps({"event": "inference_failed", "code": proc.returncode, "reason": error}), flush=True)
                    return self.reply(502, {"error": error})
                if not answer_path.is_file() or answer_path.stat().st_size > 512000 or len(stdout) > 512000:
                    return self.reply(502, {"error": "provider_output_limit"})
                answer = json.loads(answer_path.read_text())
                return self.reply(200, {"answer": answer, "events": stdout.decode("utf8", "replace")})
        except subprocess.TimeoutExpired:
            if proc:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
            return self.reply(504, {"error": "provider_timeout"})
        except Exception:
            if proc and proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
            return self.reply(502, {"error": "provider_invalid_response"})
        finally:
            LOCK.release()


ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()

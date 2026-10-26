"""Bounded model-provider adapters. Imported educational text is *data*, never commands."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field


class AIRequest(BaseModel):
    system: str
    prompt: str
    model: str
    max_output_tokens: int = Field(default=4096, ge=1, le=32768)
    response_schema: dict[str, Any] | None = None


class AIResult(BaseModel):
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderError(Exception):
    """Safe, machine-readable failure; never contains provider stderr or secrets."""

    def __init__(self, code: str, retryable: bool = False):
        super().__init__(code)
        self.code, self.retryable = code, retryable


class AIProvider(Protocol):
    async def generate(self, request: AIRequest) -> AIResult: ...


class DisabledProvider:
    async def generate(self, request: AIRequest) -> AIResult:
        raise ProviderError("provider_unconfigured")


async def _bounded_read(stream: asyncio.StreamReader, maximum: int) -> bytes:
    collected = bytearray()
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return bytes(collected)
        if len(collected) + len(chunk) > maximum:
            raise ProviderError("provider_output_limit")
        collected.extend(chunk)


class CodexCLIProvider:
    """Only launch through an operator-supplied isolated runner in production.

    Runner contract: absolute executable accepting the same argv as 'codex'.
    It must enforce non-root UID, per-request container, restricted mounts/egress,
    no host secrets or host socket, CPU/memory quotas, and a dedicated credential.
    CLI's internal sandbox alone is NOT a sufficient isolation boundary.
    """

    def __init__(self, runner: str | None = None, timeout: int = 120, concurrency: int = 2):
        self.runner = runner or os.environ.get("AI_CODEX_RUNNER")
        self.timeout = max(5, min(timeout, 600))
        self.semaphore = asyncio.Semaphore(max(1, min(concurrency, 8)))
        self._flags: set[str] | None = None

    async def _verify(self) -> None:
        if not self.runner:
            raise ProviderError("codex_isolated_runner_required")
        from app.core.config import get_settings
        if (get_settings().app_env == "production"
                and os.environ.get("AI_CODEX_ISOLATION_ATTESTED") != "1"):
            raise ProviderError("codex_production_isolation_unverified")
        if not Path(self.runner).is_absolute() or not os.access(self.runner, os.X_OK):
            raise ProviderError("codex_runner_unavailable")
        if self._flags is not None:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                self.runner, "exec", "--help",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
            )
            output, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except (OSError, asyncio.TimeoutError):
            raise ProviderError("codex_runner_unavailable") from None
        if proc.returncode != 0:
            raise ProviderError("codex_runner_unavailable")
        text = output.decode("utf-8", "replace")
        required = ("--output-schema", "--sandbox", "--skip-git-repo-check", "--model")
        if not all(flag in text for flag in required):
            raise ProviderError("codex_cli_incompatible")
        self._flags = set(required)

    async def generate(self, request: AIRequest) -> AIResult:
        if request.response_schema is None:
            raise ProviderError("json_schema_required")
        async with self.semaphore:
            await self._verify()
            with tempfile.TemporaryDirectory(prefix="somaloom-codex-") as directory:
                schema_path = Path(directory) / "schema.json"
                schema_path.write_text(json.dumps(request.response_schema))
                argv = [
                    self.runner, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
                    "--output-schema", str(schema_path), "--model", request.model, "-",
                ]
                # Isolated runner MUST safely remap/allow only the schema file and ephemeral CWD.
                prompt = (
                    request.system + "\n\nOnly produce valid JSON for the supplied schema.\n"
                    + request.prompt
                ).encode("utf-8")
                if len(prompt) > 220_000:
                    raise ProviderError("provider_input_limit")
                env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": directory,
                       "LANG": "C.UTF-8"}
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *argv, cwd=directory, env=env, stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        start_new_session=True,
                    )
                except OSError:
                    raise ProviderError("codex_runner_unavailable") from None
                try:
                    proc.stdin.write(prompt)
                    await proc.stdin.drain()
                    proc.stdin.close()
                    async def collect():
                        stdout, stderr = await asyncio.gather(
                            _bounded_read(proc.stdout, 512_000),
                            _bounded_read(proc.stderr, 32_000),
                        )
                        await proc.wait()
                        return stdout, stderr
                    stdout, stderr = await asyncio.wait_for(collect(), timeout=self.timeout)
                except (asyncio.TimeoutError, asyncio.CancelledError, ProviderError) as err:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await proc.wait()
                    if isinstance(err, asyncio.CancelledError):
                        raise
                    if isinstance(err, ProviderError):
                        raise
                    raise ProviderError("provider_timeout", retryable=True) from None
                if proc.returncode:
                    reason = stderr.decode("utf-8", "replace").lower()
                    if "unauthorized" in reason or "login" in reason or "token expired" in reason:
                        raise ProviderError("provider_auth_expired")
                    raise ProviderError("provider_execution_failed", retryable=proc.returncode in (1, 75))
                raw = stdout.decode("utf-8", "replace").strip()
                try:
                    json.loads(raw)
                except ValueError:
                    raise ProviderError("provider_invalid_json") from None
                return AIResult(text=raw, provider="codex", model=request.model)


class OpenAIAPIProvider:
    """Independently billed server-side, OpenAI-compatible chat-completions fallback."""

    def __init__(self, api_key: str | None = None, endpoint: str | None = None, timeout: int = 90):
        self.api_key = api_key or os.environ.get("AI_API_KEY", "")
        self.endpoint = endpoint or os.environ.get(
            "AI_API_ENDPOINT", "https://api.openai.com/v1/chat/completions"
        )
        self.timeout = max(5, min(timeout, 180))
        if not self.endpoint.startswith("https://"):
            raise ProviderError("provider_endpoint_insecure")

    async def generate(self, request: AIRequest) -> AIResult:
        if not self.api_key:
            raise ProviderError("provider_auth_missing")
        if request.response_schema is None:
            raise ProviderError("json_schema_required")
        payload = json.dumps({
            "model": request.model,
            "messages": [{"role": "system", "content": request.system},
                         {"role": "user", "content": request.prompt}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "somaloom_section", "strict": True, "schema": request.response_schema}},
            "max_completion_tokens": request.max_output_tokens,
        }).encode()
        def perform() -> dict:
            req = urllib.request.Request(
                self.endpoint, payload,
                {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    if int(response.headers.get("Content-Length", "0")) > 512_000:
                        raise ProviderError("provider_output_limit")
                    raw = response.read(512_001)
                    if len(raw) > 512_000:
                        raise ProviderError("provider_output_limit")
                    return json.loads(raw)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise ProviderError("provider_auth_expired") from None
                if e.code == 429 or e.code >= 500:
                    raise ProviderError("provider_rate_or_upstream", retryable=True) from None
                raise ProviderError("provider_request_rejected") from None
            except (urllib.error.URLError, TimeoutError):
                raise ProviderError("provider_unreachable", retryable=True) from None
        data = await asyncio.to_thread(perform)
        try:
            message = data["choices"][0]["message"]["content"]
            json.loads(message)
            usage = data.get("usage") or {}
            return AIResult(text=message, provider="api", model=request.model,
                            input_tokens=int(usage.get("prompt_tokens") or 0),
                            output_tokens=int(usage.get("completion_tokens") or 0))
        except (KeyError, IndexError, ValueError, TypeError):
            raise ProviderError("provider_invalid_json") from None


class FallbackProvider:
    def __init__(self, primary: AIProvider, fallback: AIProvider):
        self.primary, self.fallback = primary, fallback

    async def generate(self, request: AIRequest) -> AIResult:
        try:
            return await self.primary.generate(request)
        except ProviderError as error:
            if error.code in {"provider_invalid_json", "json_schema_required", "provider_input_limit"}:
                raise
            return await self.fallback.generate(request)


def provider_available(name: str) -> bool:
    from app.core.config import get_settings
    codex_ready = bool(os.getenv("AI_CODEX_RUNNER"))
    if get_settings().app_env == "production":
        codex_ready = codex_ready and os.getenv("AI_CODEX_ISOLATION_ATTESTED") == "1"
    if name == "codex":
        return codex_ready
    if name == "api":
        return bool(os.getenv("AI_API_KEY"))
    if name == "codex_with_api_fallback":
        return codex_ready or bool(os.getenv("AI_API_KEY"))
    return False


def configured_provider(name: str) -> AIProvider:
    if name == "codex":
        return CodexCLIProvider()
    if name == "api":
        return OpenAIAPIProvider()
    if name == "codex_with_api_fallback":
        if not os.getenv("AI_CODEX_RUNNER"):
            return OpenAIAPIProvider()
        return FallbackProvider(CodexCLIProvider(), OpenAIAPIProvider())
    return DisabledProvider()

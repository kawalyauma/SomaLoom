"""Agent 5 implements configured runtime providers; no developer credentials here."""
from typing import Protocol
from pydantic import BaseModel

class AIRequest(BaseModel):
    system: str
    prompt: str
    model: str
    max_output_tokens: int = 4096

class AIResult(BaseModel):
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0

class AIProvider(Protocol):
    async def generate(self, request: AIRequest) -> AIResult: ...

class DisabledProvider:
    async def generate(self, request: AIRequest) -> AIResult:
        raise RuntimeError("Runtime AI provider is not configured")

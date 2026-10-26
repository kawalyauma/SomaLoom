"""Optional, dimension-checked embeddings. Never use Codex CLI credentials."""
import json
import os
from dataclasses import dataclass
from urllib.request import Request, urlopen

DIMENSIONS = 1536
MODEL = "text-embedding-3-small"

@dataclass(frozen=True)
class Embeddings:
    model: str = MODEL
    dimensions: int = DIMENSIONS

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.model != MODEL or self.dimensions != DIMENSIONS:
            raise ValueError("Embedding model/dimension incompatible with vector(1536)")
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY missing; semantic retrieval is unavailable")
        if not texts:
            return []
        # Fixed vendor URL: do not accept arbitrary URLs or use developer CLI login.
        payload = json.dumps({"input": texts, "model": self.model,
                              "dimensions": self.dimensions}).encode()
        req = Request("https://api.openai.com/v1/embeddings", data=payload,
                      headers={"Authorization": f"Bearer {key}",
                               "Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=25) as response:
            body = json.load(response)
        ordered = sorted(body["data"], key=lambda row: row["index"])
        vectors = [row["embedding"] for row in ordered]
        if len(vectors) != len(texts):
            raise ValueError("Provider returned incorrect embedding count")
        for v in vectors:
            validate_vector(v)
        return vectors

def validate_vector(vector):
    import math
    if len(vector) != DIMENSIONS or not all(isinstance(n, (int, float)) and
            math.isfinite(n) for n in vector):
        raise ValueError("Expected 1536 finite embedding dimensions")
    return vector

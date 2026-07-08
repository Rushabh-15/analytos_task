"""Chunk-embedding client.

Deliberately reads the SAME environment contract as omnigraph-server's
query-time embedder (OMNIGRAPH_EMBED_PROVIDER / _MODEL / _BASE_URL plus the
provider API keys), so the vectors this pipeline stores and the vectors the
server computes for `nearest($c.embedding, $q)` come from one model — one
vector space. Change the env once, both sides follow.

Providers:
  * mock              — deterministic, keyless. Local dev / CI. (Note: the
                        engine's own mock is a different deterministic
                        function, so local semantic ranking is placeholder
                        quality; BM25 carries local search. Use a real
                        provider for the hosted demo.)
  * gemini            — generativelanguage embedContent, outputDimensionality=DIM
  * openai            — api.openai.com /embeddings with dimensions=DIM
  * openai-compatible — any /embeddings endpoint (OpenRouter default)
"""
from __future__ import annotations

import hashlib
import math
import os
import struct
from typing import List

import requests

DIM = 768  # must match Vector(768) in knowledge.pg


def _l2(vec: List[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def _mock_embed(text: str) -> List[float]:
    """Deterministic pseudo-embedding: SHA-512 stream -> floats."""
    out: List[float] = []
    counter = 0
    seed = text.encode("utf-8", errors="ignore")
    while len(out) < DIM:
        h = hashlib.sha512(seed + counter.to_bytes(4, "big")).digest()
        for i in range(0, len(h) - 3, 4):
            (u,) = struct.unpack(">I", h[i:i + 4])
            out.append((u / 0xFFFFFFFF) * 2.0 - 1.0)
            if len(out) == DIM:
                break
        counter += 1
    return _l2(out)


class Embedder:
    def __init__(self) -> None:
        self.provider = os.getenv("OMNIGRAPH_EMBED_PROVIDER", "mock").strip().lower()
        self.model = os.getenv("OMNIGRAPH_EMBED_MODEL", "")
        self.base_url = os.getenv("OMNIGRAPH_EMBED_BASE_URL", "")

    def describe(self) -> str:
        return f"{self.provider}:{self.model or 'default-model'}"

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self.provider == "mock":
            return [_mock_embed(t) for t in texts]
        if self.provider == "gemini":
            return self._gemini(texts)
        if self.provider in ("openai", "openai-compatible"):
            return self._openai_style(texts)
        raise ValueError(f"Unknown OMNIGRAPH_EMBED_PROVIDER: {self.provider}")

    # ── real providers ──────────────────────────────────────
    def _gemini(self, texts: List[str]) -> List[List[float]]:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise EnvironmentError("GEMINI_API_KEY is required for provider=gemini")
        model = self.model or "gemini-embedding-2"
        base = self.base_url or "https://generativelanguage.googleapis.com/v1beta"
        out: List[List[float]] = []
        for t in texts:
            r = requests.post(
                f"{base}/models/{model}:embedContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={
                    "content": {"parts": [{"text": t[:8000]}]},
                    "taskType": "RETRIEVAL_DOCUMENT",
                    "outputDimensionality": DIM,
                },
                timeout=60,
            )
            r.raise_for_status()
            out.append(_l2(r.json()["embedding"]["values"]))
        return out

    def _openai_style(self, texts: List[str]) -> List[List[float]]:
        if self.provider == "openai":
            base = self.base_url or "https://api.openai.com/v1"
            key = os.getenv("OPENAI_API_KEY")
            model = self.model or "text-embedding-3-small"
        else:
            base = self.base_url or "https://openrouter.ai/api/v1"
            key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
            model = self.model or "openai/text-embedding-3-small"
        if not key:
            raise EnvironmentError("OPENAI_API_KEY / OPENROUTER_API_KEY required")
        out: List[List[float]] = []
        for i in range(0, len(texts), 64):
            batch = [t[:8000] for t in texts[i:i + 64]]
            r = requests.post(
                f"{base}/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "input": batch, "dimensions": DIM},
                timeout=120,
            )
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            out.extend(_l2(d["embedding"]) for d in data)
        return out

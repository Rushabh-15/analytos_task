"""LLM extraction step: document text -> ExtractionResult.

Providers (EXTRACT_PROVIDER env, or auto-detected from available keys):
  * anthropic — Claude (default model claude-haiku-4-5-20251001)
  * openai    — GPT (default model gpt-4o-mini)
  * gemini    — Gemini (default model gemini-2.0-flash)
  * fixture   — reads fixtures/<filename>.json; deterministic, keyless.
                Used by tests/CI and by `make seed-fixture` so the whole
                loop runs with zero API keys.

All real providers run at temperature 0 with a JSON-only instruction; output
is validated by pydantic before anything is loaded into the graph.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests

from .model import ExtractionResult
from .prompts import EXTRACTION_SYSTEM, user_prompt

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _detect_provider() -> str:
    explicit = os.getenv("EXTRACT_PROVIDER")
    if explicit:
        return explicit.strip().lower()
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return "fixture"


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return m.group(1) if m else text


def _anthropic(filename: str, content: str) -> str:
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": os.getenv("EXTRACT_MODEL", "claude-haiku-4-5-20251001"),
            "max_tokens": 8000,
            "temperature": 0,
            "system": EXTRACTION_SYSTEM,
            "messages": [{"role": "user", "content": user_prompt(filename, content)}],
        },
        timeout=180,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])


def _openai(filename: str, content: str) -> str:
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={
            "model": os.getenv("EXTRACT_MODEL", "gpt-4o-mini"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user", "content": user_prompt(filename, content)},
            ],
        },
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _gemini(filename: str, content: str) -> str:
    model = os.getenv("EXTRACT_MODEL", "gemini-2.0-flash")
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"],
                 "Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": EXTRACTION_SYSTEM}]},
            "contents": [{"parts": [{"text": user_prompt(filename, content)}]}],
            "generationConfig": {"temperature": 0,
                                 "responseMimeType": "application/json"},
        },
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _fixture(filename: str) -> str:
    path = FIXTURES_DIR / f"{Path(filename).stem}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"fixture mode: no fixture for '{filename}' at {path}. "
            "Set an LLM key (ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY) "
            "or add a fixture."
        )
    return path.read_text()


def extract(filename: str, content: str) -> ExtractionResult:
    provider = _detect_provider()
    if provider == "fixture":
        raw = _fixture(filename)
    elif provider == "anthropic":
        raw = _anthropic(filename, content)
    elif provider == "openai":
        raw = _openai(filename, content)
    elif provider == "gemini":
        raw = _gemini(filename, content)
    else:
        raise ValueError(f"Unknown EXTRACT_PROVIDER: {provider}")
    data = json.loads(_strip_fences(raw))
    result = ExtractionResult.model_validate(data)
    return result


def provider_name() -> str:
    return _detect_provider()

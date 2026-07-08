"""Minimal LLM completion for agents (anthropic/openai/gemini), with an
explicit 'none' mode so agents degrade to deterministic templates and the
demo never depends on an API key."""
from __future__ import annotations

import os

import requests


def provider() -> str:
    p = os.getenv("AGENT_PROVIDER") or os.getenv("EXTRACT_PROVIDER")
    if p and p.lower() != "fixture":
        return p.lower()
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return "none"


def complete(system: str, user: str, max_tokens: int = 4000) -> str:
    p = provider()
    if p == "anthropic":
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                     "anthropic-version": "2023-06-01"},
            json={"model": os.getenv("AGENT_MODEL", "claude-sonnet-4-5"),
                  "max_tokens": max_tokens, "temperature": 0.4,
                  "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=240)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    if p == "openai":
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={"model": os.getenv("AGENT_MODEL", "gpt-4o"),
                  "temperature": 0.4,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=240)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    if p == "gemini":
        model = os.getenv("AGENT_MODEL", "gemini-2.0-flash")
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            json={"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"parts": [{"text": user}]}],
                  "generationConfig": {"temperature": 0.4}},
            timeout=240)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise RuntimeError("no LLM provider configured")

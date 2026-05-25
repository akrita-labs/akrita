"""
Minimal OpenAI-compatible chat client for the configured reasoner model.

This is the thin transport the agents' reasoning layers use (NOMOS rug
assessment today, SPATHA conviction later). One async call, a tolerant JSON
parser, and graceful degradation: the agent must NEVER crash on a malformed or
unreachable model — every caller falls back to deterministic logic. So when the
model is up, the AI genuinely decides; when it is down, the rules still hold.
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

import httpx

from shared.config import settings


def reasoner_configured() -> bool:
    """True when a base URL, credential and model are all set."""
    return bool(
        settings.llm_base_url
        and (settings.llm_api_key or settings.llm_auth_token)
        and settings.akrita_reasoner_model
    )


def reasoner_model() -> str:
    return settings.akrita_reasoner_model or "unset"


def _auth() -> str:
    return settings.llm_api_key or settings.llm_auth_token


def _parse_json(text: str) -> dict:
    """Extract a JSON object from a model response, tolerating code fences and
    leading/trailing prose. Raises ValueError if no object can be recovered."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise ValueError(f"no JSON object in model response: {text[:120]!r}")


async def chat_json(
    system: str,
    user: str,
    *,
    timeout: float = 40.0,
    max_tokens: int = 800,
    temperature: float = 0.1,
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[dict, int]:
    """Call the reasoner and return (parsed_json, latency_ms).

    Raises on transport error, non-2xx, or unparseable output — callers catch
    and fall back. We do NOT send `response_format` (not all OpenAI-compatible
    gateways accept it); the prompt asks for JSON and the parser is tolerant.
    """
    if not reasoner_configured():
        raise RuntimeError("reasoner not configured")
    own = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    base = settings.llm_base_url.rstrip("/")
    payload = {
        "model": settings.akrita_reasoner_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    t0 = time.monotonic()
    try:
        r = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {_auth()}", "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    finally:
        if own:
            await client.aclose()
    latency_ms = int((time.monotonic() - t0) * 1000)
    return _parse_json(content), latency_ms

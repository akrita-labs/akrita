"""
AGROS — autonomous bond resolver: closes the prediction-market loop honestly.

For each open predictive claim, AGROS checks the token's REAL live market (via
DEXScreener: liquidity + price action) and decides whether the prediction has
resolved — rugged (liquidity collapsed / catastrophic drop), held (window elapsed
and still healthy), or still open. The reasoner makes the call, but the policy is
deliberately conservative: AGROS only settles real bonds on clear evidence and
never manufactures an outcome. A claim whose token is still trading stays open —
that is the honest result, even though it adds no settlement volume.

Pure parsing/policy is import-safe; the DEXScreener fetch and the model call both
degrade gracefully.
"""
from __future__ import annotations

import json
import time
from typing import Optional

import httpx

from shared.llm import chat_json, reasoner_configured, reasoner_model

DEX_TOKENS = "https://api.dexscreener.com/latest/dex/tokens/"

# Liquidity at or below this (USD) on a token that was promoted onto a DEX is
# treated as a hard rug signal (pool pulled / never real).
RUG_LIQUIDITY_USD = 1_000.0

_SYSTEM = (
    "You are AGROS, the bond-settlement agent for the AKRITA rug-risk oracle. A "
    "predictive claim said a flagged token would drop past a threshold within a "
    "window. You are given the claim and the token's CURRENT live DEX market. "
    "Decide whether the prediction has resolved.\n\n"
    "Resolve 'rugged' ONLY on clear evidence the token rugged: collapsed/near-zero "
    "liquidity, or a catastrophic price drop past the threshold. Resolve 'held' ONLY "
    "if the window has elapsed and the token is still healthy. Otherwise 'open' — do "
    "not guess, do not settle a live, still-trading token early. Honesty over volume.\n\n"
    "Output ONLY a JSON object with exactly these keys:\n"
    '{"outcome": "rugged" | "held" | "open", "confidence": 0.0-1.0, '
    '"rationale": "<= 2 sentences citing the market evidence"}'
)


async def fetch_market(address: str, *, client: Optional[httpx.AsyncClient] = None) -> dict:
    """Live market snapshot for a token: best-pair liquidity + price action.
    Returns {has_pairs, liquidity_usd, price_usd, change_h24, change_h6}."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "akrita-agros"})
    try:
        r = await client.get(DEX_TOKENS + address)
        pairs = (r.json() or {}).get("pairs") or [] if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        pairs = []
    finally:
        if own:
            await client.aclose()
    if not pairs:
        return {"has_pairs": False, "liquidity_usd": 0.0, "price_usd": None, "change_h24": None, "change_h6": None}
    best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    ch = best.get("priceChange") or {}
    return {
        "has_pairs": True,
        "liquidity_usd": float((best.get("liquidity") or {}).get("usd") or 0),
        "price_usd": best.get("priceUsd"),
        "change_h24": ch.get("h24"),
        "change_h6": ch.get("h6"),
    }


def window_elapsed(issued_at: int, window_s: int) -> bool:
    return window_s > 0 and (int(issued_at) + int(window_s)) < int(time.time())


def _deterministic_outcome(market: dict, claim: dict) -> dict:
    """Conservative rules used when the reasoner is offline."""
    if market.get("has_pairs") and 0 < market.get("liquidity_usd", 0) <= RUG_LIQUIDITY_USD:
        return {"outcome": "rugged", "confidence": 0.8,
                "rationale": f"Liquidity collapsed to ${market['liquidity_usd']:.0f} — pool effectively pulled."}
    if not market.get("has_pairs"):
        return {"outcome": "open", "confidence": 0.0,
                "rationale": "No DEX pair indexed — insufficient evidence to settle."}
    if window_elapsed(claim.get("issued_at", 0), claim.get("window_s", 0)):
        return {"outcome": "held", "confidence": 0.6,
                "rationale": "Window elapsed and the token still has an active market."}
    return {"outcome": "open", "confidence": 0.0, "rationale": "Token still trading; window open."}


async def assess_resolution(
    claim: dict,
    nomos_summary: dict,
    market: dict,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Decide rugged / held / open for one claim, conservatively."""
    base = _deterministic_outcome(market, claim)
    if not reasoner_configured():
        base["decided_by"] = "deterministic"
        return base
    payload = {
        "claim": {
            "token": nomos_summary.get("token"),
            "reasons": nomos_summary.get("reasons", []),
            "window_s": claim.get("window_s"),
            "drop_threshold_bps": claim.get("drop_threshold_bps"),
            "window_elapsed": window_elapsed(claim.get("issued_at", 0), claim.get("window_s", 0)),
        },
        "market": market,
    }
    try:
        verdict, ms = await chat_json(_SYSTEM, "Resolve this claim:\n" + json.dumps(payload, separators=(",", ":")),
                                      client=client, max_tokens=300)
    except Exception:
        base["decided_by"] = "deterministic"
        return base
    outcome = str(verdict.get("outcome", "")).strip().lower()
    if outcome not in ("rugged", "held", "open"):
        outcome = base["outcome"]
    return {
        "decided_by": f"reasoner:{reasoner_model()}",
        "outcome": outcome,
        "confidence": max(0.0, min(1.0, float(verdict.get("confidence", 0.5) or 0.5))),
        "rationale": str(verdict.get("rationale") or "").strip()[:400],
        "model": reasoner_model(),
        "latency_ms": ms,
    }

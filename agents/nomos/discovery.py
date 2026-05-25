"""
NOMOS — self-directed target discovery: the agent picks what to investigate.

Instead of screening a human-curated watchlist, NOMOS pulls freshly-promoted and
trending tokens from DEXScreener (a live market feed, no key needed), then the LLM
TRIAGES them — deciding which look most worth a deep rug-risk screen, and why.
This is the goal-seeking layer: the agent chooses its own targets from the open
market, then runs the same honest GoPlus + reasoner issue/skip decision on each.

Pure parsing/mapping is import-safe; the network edges (fetch) and the model edge
(triage) both degrade gracefully so a discovery loop never crashes.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx

from shared.llm import chat_json, reasoner_configured, reasoner_model

DEX_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEX_BOOSTS = "https://api.dexscreener.com/token-boosts/latest/v1"

# DEXScreener chain slug -> GoPlus token-security numeric chain id (EVM only;
# GoPlus screens these). Non-EVM (e.g. solana) candidates are dropped.
CHAIN_IDS = {
    "ethereum": 1,
    "bsc": 56,
    "polygon": 137,
    "base": 8453,
    "arbitrum": 42161,
    "optimism": 10,
    "avalanche": 43114,
    "fantom": 250,
}

_TRIAGE_SYSTEM = (
    "You are NOMOS, the rug-risk analyst for the AKRITA oracle. You are handed a list "
    "of freshly-promoted tokens from a DEX feed and a limited screening budget. Decide "
    "which ones are most worth a deep on-chain rug-risk screen, and which to skip.\n\n"
    "Prioritize tokens that show classic rug/scam risk signals: anonymous or hype-driven "
    "descriptions, vague or absent utility, pump-style naming, brand-new promotion. "
    "Deprioritize tokens that read as established, reputable, or clearly utility-bearing. "
    "You are only triaging what to investigate — the actual rug verdict comes from a "
    "later token-security screen, so when in doubt about a risky-looking token, include it.\n\n"
    "Output ONLY a JSON object with exactly these keys:\n"
    '{"selected": [{"address": "0x..", "reason": "<short why worth screening>"}], '
    '"rationale": "<= 2 sentences on how you prioritized"}'
)


async def fetch_candidates(
    *,
    limit: int = 40,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict]:
    """Pull freshly-promoted + boosted tokens, dedup, keep GoPlus-screenable EVM
    ones. Returns [] on failure so a loop degrades gracefully."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "akrita-nomos"})
    out: dict[str, dict] = {}
    try:
        for url in (DEX_PROFILES, DEX_BOOSTS):
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                for item in r.json() or []:
                    chain = item.get("chainId")
                    addr = (item.get("tokenAddress") or "").lower()
                    if chain not in CHAIN_IDS or not addr.startswith("0x") or addr in out:
                        continue
                    out[addr] = {
                        "address": addr,
                        "chain": chain,
                        "chain_id": CHAIN_IDS[chain],
                        "description": (item.get("description") or "").replace("\n", " ")[:200],
                        "url": item.get("url", ""),
                    }
            except (httpx.HTTPError, ValueError):
                continue
    finally:
        if own:
            await client.aclose()
    return list(out.values())[:limit]


async def triage(
    candidates: list[dict],
    *,
    max_select: int = 5,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """LLM picks which candidates to deep-screen (with reasoning). Falls back to
    taking the first `max_select` when the reasoner is unavailable."""
    if not candidates:
        return {"decided_by": "none", "selected": [], "rationale": "no candidates", "considered": 0}
    by_addr = {c["address"]: c for c in candidates}
    if not reasoner_configured():
        sel = candidates[:max_select]
        return {
            "decided_by": "deterministic",
            "selected": sel,
            "rationale": "Reasoner offline — took the first candidates.",
            "considered": len(candidates),
        }
    payload = [{"address": c["address"], "chain": c["chain"], "description": c["description"]} for c in candidates]
    user = (
        f"You may deep-screen at most {max_select} of these {len(candidates)} freshly-promoted "
        "tokens. Select the ones most worth investigating for rug risk:\n"
        + json.dumps(payload, separators=(",", ":"))
    )
    try:
        verdict, ms = await chat_json(_TRIAGE_SYSTEM, user, client=client, max_tokens=600)
    except Exception:
        sel = candidates[:max_select]
        return {
            "decided_by": "deterministic",
            "selected": sel,
            "rationale": "Reasoner unavailable — took the first candidates.",
            "considered": len(candidates),
        }
    selected: list[dict] = []
    for item in (verdict.get("selected") or [])[:max_select]:
        addr = str(item.get("address", "")).lower()
        if addr in by_addr:
            c = dict(by_addr[addr])
            c["triage_reason"] = str(item.get("reason") or "")[:160]
            selected.append(c)
    return {
        "decided_by": f"reasoner:{reasoner_model()}",
        "selected": selected,
        "rationale": str(verdict.get("rationale") or "").strip()[:300],
        "considered": len(candidates),
        "model": reasoner_model(),
        "latency_ms": ms,
    }

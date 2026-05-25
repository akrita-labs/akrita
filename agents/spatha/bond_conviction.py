"""
SPATHA — autonomous bond conviction for the Rugpull Oracle.

After NOMOS issues a rug-risk claim, SPATHA independently decides whether AKRITA
should put its own capital behind that conviction: back it (the token rugs), fade
it (it holds), or abstain. SPATHA reasons separately from NOMOS — a second
opinion, not a rubber stamp — and can decline even a claim NOMOS issued. The
size is confidence-scaled and hard-capped, so the agent acts autonomously within
a fixed budget it can never exceed.

The decision is the agency. The on-chain stake (ClaimRegistryReal.stake) is gated
on the SPATHA keeper holding USDC on Arc; when unfunded, SPATHA still decides and
records its conviction, and the execution is reported as gated.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx

from shared.llm import chat_json, reasoner_configured, reasoner_model

# SPATHA will only commit capital at or above this conviction.
MIN_CONVICTION_TO_STAKE = 0.6
_SEVERITY_WEIGHT = {"low": 0.25, "medium": 0.5, "high": 0.8, "critical": 1.0}

_SYSTEM = (
    "You are SPATHA, the risk sentinel of the AKRITA oracle. NOMOS has issued a "
    "signed, on-chain rug-risk claim about a token and you must decide whether "
    "AKRITA stakes its OWN USDC behind it. You are a second opinion, not a rubber "
    "stamp: back the claim only if NOMOS's evidence genuinely convinces you the "
    "token will rug; fade it if you think NOMOS over-reached; abstain when it is "
    "too uncertain to risk capital. Be disciplined — this is real money on a "
    "two-sided bond market where the losing side is slashed.\n\n"
    "Output ONLY a JSON object with exactly these keys:\n"
    '{"position": "back" | "fade" | "abstain", "conviction": 0.0-1.0, '
    '"rationale": "<= 2 sentences"}'
)


def _clamp(v, lo=0.0, hi=1.0, default=0.5) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


async def assess_conviction(
    claim_summary: dict,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """SPATHA's independent judgment on whether to stake. Falls back to a
    confidence-mirroring heuristic when the reasoner is unavailable."""
    if not reasoner_configured():
        # Heuristic: mirror NOMOS confidence, lean to back, never abstain hard.
        nconf = _clamp(claim_summary.get("nomos_confidence"), default=0.0)
        return {
            "decided_by": "deterministic",
            "position": "back" if nconf >= MIN_CONVICTION_TO_STAKE else "abstain",
            "conviction": nconf,
            "rationale": "Heuristic: mirrors NOMOS confidence (reasoner offline).",
            "model": None,
            "latency_ms": 0,
        }
    user = "Decide on this issued claim:\n" + json.dumps(claim_summary, separators=(",", ":"))
    try:
        verdict, ms = await chat_json(_SYSTEM, user, client=client, max_tokens=300)
    except Exception:
        nconf = _clamp(claim_summary.get("nomos_confidence"), default=0.0)
        return {
            "decided_by": "deterministic",
            "position": "back" if nconf >= MIN_CONVICTION_TO_STAKE else "abstain",
            "conviction": nconf,
            "rationale": "Heuristic fallback: reasoner unavailable.",
            "model": None,
            "latency_ms": 0,
        }
    position = str(verdict.get("position", "")).strip().lower()
    if position not in ("back", "fade", "abstain"):
        position = "abstain"
    return {
        "decided_by": f"reasoner:{reasoner_model()}",
        "position": position,
        "conviction": _clamp(verdict.get("conviction")),
        "rationale": str(verdict.get("rationale") or "").strip()[:400],
        "model": reasoner_model(),
        "latency_ms": ms,
    }


def size_stake(conviction: float, severity: str, *, max_stake_usdc: float) -> float:
    """Confidence- and severity-scaled stake, hard-capped at `max_stake_usdc`.
    Returns 0.0 below the conviction floor."""
    c = _clamp(conviction, default=0.0)
    if c < MIN_CONVICTION_TO_STAKE:
        return 0.0
    weight = _SEVERITY_WEIGHT.get(str(severity or "").lower(), 0.5)
    return round(max(0.0, max_stake_usdc * c * weight), 2)


def conviction_plan(claim_summary: dict, conviction: dict, *, max_stake_usdc: float) -> dict:
    """Combine SPATHA's judgment with the sizing policy into an actionable plan.
    `position` back→stake FOR (rugs), fade→stake AGAINST (holds), abstain→none."""
    position = conviction.get("position", "abstain")
    if position == "abstain":
        return {"action": "none", "position": position, "amount_usdc": 0.0,
                "reason": conviction.get("rationale", "")}
    amount = size_stake(conviction.get("conviction", 0.0), claim_summary.get("severity"),
                        max_stake_usdc=max_stake_usdc)
    if amount <= 0:
        return {"action": "none", "position": position, "amount_usdc": 0.0,
                "reason": "below conviction floor"}
    return {
        "action": "stake",
        "position": position,
        "backs_claim": position == "back",
        "amount_usdc": amount,
        "amount_base_units": int(round(amount * 1_000_000)),  # USDC 6 decimals
        "reason": conviction.get("rationale", ""),
    }

"""
NOMOS — LLM rug-risk reasoner: the agentic decision layer.

The deterministic GoPlus rules (goplus_screen.evaluate_risk) are the *guardrail*
and the *fallback*. This module is the *decider*: it sends the structured signal
to the configured reasoner model and gets back a genuine judgment — issue or
skip, a confidence, a severity, and a written rationale that becomes load-bearing
in the on-chain trace. If the model is unreachable or returns garbage, NOMOS
falls back to the deterministic verdict so the oracle never breaks; but when the
model is up, the AI actually decides — and the trace records who decided.

Two guardrails keep the agency honest:
  1. The model is told the honest-rules contract (ordinary admin functions on
     USDT/USDC/PEPE are NOT a rug) — so it cannot flag a blue-chip stablecoin.
  2. Code-side, a token the deterministic rules did NOT flag can only be issued
     by the model at high conviction (>= ISSUE_BEYOND_RULES_CONFIDENCE). The
     model may extend the rules, never quietly override the safe default.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx

from shared.llm import chat_json, reasoner_configured, reasoner_model

# A token the rules left UNFLAGGED can only be issued by the model when it is at
# least this confident — the rules stay the floor, the model only extends upward.
ISSUE_BEYOND_RULES_CONFIDENCE = 0.75

_SEVERITY = ("low", "medium", "high", "critical")

_TOKEN_SYSTEM = (
    "You are NOMOS, the rug-risk analyst for the AKRITA on-chain oracle. You are "
    "given a token's GoPlus token-security record and a deterministic rule verdict. "
    "Decide whether AKRITA should issue a SIGNED, ON-CHAIN rug-risk claim about this "
    "token — a public accusation anchored on Arc, so a false positive is costly.\n\n"
    "HONEST-RULES CONTRACT (do not violate):\n"
    "- A genuine rug/scam means holders will likely lose funds: honeypot (cannot "
    "sell), cannot-sell-all, hidden owner, self-destruct, creator linked to other "
    "honeypots, or scam-level transfer tax (>=50%).\n"
    "- Ordinary admin capabilities — blacklist function, pausable transfers, "
    "mintable supply, ownership controls — are present in MANY legitimate tokens "
    "(USDT, USDC, PEPE). These are CONTEXT, never a rug on their own. Never issue a "
    "claim against an established blue-chip token for having admin functions.\n"
    "- When the evidence is genuinely a scam pattern, do not hedge; issue. When it "
    "is ordinary, skip. Be decisive and be honest.\n\n"
    "Output ONLY a JSON object, no prose, with exactly these keys:\n"
    '{"decision": "issue" | "skip", "confidence": 0.0-1.0, '
    '"severity": "low"|"medium"|"high"|"critical", '
    '"rationale": "<= 3 sentences explaining the call in plain English", '
    '"key_factors": ["short", "evidence", "phrases"]}'
)

_FREEZE_SYSTEM = (
    "You are NOMOS, the on-chain analyst for the AKRITA oracle. A stablecoin issuer "
    "(Tether/USDT or Circle/USDC) has FROZEN an address on Ethereum via its blacklist "
    "function — an immutable on-chain fact. Issuers freeze addresses for sanctions "
    "(OFAC), law-enforcement seizure, hack/exploit proceeds, or fraud. You are not "
    "deciding whether to attest (the freeze is a hard fact AKRITA always attests); "
    "you are writing the interpretation that will live in the on-chain trace.\n\n"
    "Output ONLY a JSON object with exactly these keys:\n"
    '{"severity": "low"|"medium"|"high"|"critical", '
    '"likely_cause": "<short phrase: sanctions / hack proceeds / fraud / seizure / unknown>", '
    '"rationale": "<= 2 sentences interpreting this freeze for an observer"}'
)


def _clamp_conf(v) -> float:
    try:
        c = float(v)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, c))


def _norm_sev(v, fallback: str = "medium") -> str:
    s = str(v or "").strip().lower()
    return s if s in _SEVERITY else fallback


def _deterministic_fallback(risk: dict, note: str) -> dict:
    """Verdict from the rules alone — used when the reasoner is off/unreachable."""
    flagged = bool(risk.get("flagged"))
    sev_idx = min(len(risk.get("reasons", [])), 3)
    return {
        "decided_by": "deterministic",
        "decision": "issue" if flagged else "skip",
        "confidence": 0.65 if flagged else 0.0,
        "severity": _SEVERITY[sev_idx] if flagged else "low",
        "rationale": f"Deterministic rule verdict ({note}): "
        + (", ".join(risk.get("reasons", [])) or "no strong rug indicators."),
        "key_factors": list(risk.get("reasons", [])),
        "model": None,
        "latency_ms": 0,
    }


async def assess_token(
    record: dict,
    risk: dict,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Genuine issue/skip judgment on a GoPlus-screened token.

    Returns a normalized verdict dict. `decided_by` is "reasoner:<model>" when the
    model decided, "deterministic" when it fell back. The final issuance guardrail
    (rules-floor) is applied by the caller, not here.
    """
    if not reasoner_configured():
        return _deterministic_fallback(risk, "reasoner not configured")

    payload = {
        "token": record.get("token"),
        "token_name": record.get("token_name"),
        "address": record.get("address"),
        "chain_id": record.get("chain_id"),
        "deterministic_verdict": {
            "flagged": risk.get("flagged"),
            "strong_reasons": risk.get("reasons", []),
            "context_flags": risk.get("context", []),
        },
        "goplus_flags": record.get("flags", {}),
    }
    user = "Assess this token:\n" + json.dumps(payload, separators=(",", ":"))
    try:
        verdict, ms = await chat_json(_TOKEN_SYSTEM, user, client=client)
    except Exception as e:  # transport / parse / non-2xx
        return _deterministic_fallback(risk, f"reasoner unavailable: {type(e).__name__}")

    decision = str(verdict.get("decision", "")).strip().lower()
    if decision not in ("issue", "skip"):
        decision = "issue" if risk.get("flagged") else "skip"
    factors = verdict.get("key_factors") or []
    if not isinstance(factors, list):
        factors = [str(factors)]
    return {
        "decided_by": f"reasoner:{reasoner_model()}",
        "decision": decision,
        "confidence": _clamp_conf(verdict.get("confidence")),
        "severity": _norm_sev(verdict.get("severity")),
        "rationale": str(verdict.get("rationale") or "").strip()[:600]
        or "(model returned no rationale)",
        "key_factors": [str(f)[:60] for f in factors][:8],
        "model": reasoner_model(),
        "latency_ms": ms,
    }


def apply_rules_floor(assessment: dict, risk: dict) -> bool:
    """Final guardrail: should NOMOS actually issue?

    - If the deterministic rules flagged it, issue when the model also says issue.
    - If the rules did NOT flag it, the model may only issue at high conviction —
      it can extend the rules, never silently override the safe default.
    """
    if assessment.get("decision") != "issue":
        return False
    if risk.get("flagged"):
        return True
    return assessment.get("confidence", 0.0) >= ISSUE_BEYOND_RULES_CONFIDENCE


async def assess_freeze(
    rec: dict,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[dict]:
    """Best-effort interpretation of one stablecoin freeze for the trace. Returns
    None when the reasoner is off/unreachable (freeze attestation proceeds without
    it — the on-chain fact stands on its own)."""
    if not reasoner_configured():
        return None
    payload = {
        "issuer": rec.get("issuer"),
        "frozen_address": rec.get("frozen_address"),
        "freeze_tx": rec.get("freeze_tx"),
        "block": rec.get("block"),
    }
    user = "Interpret this freeze:\n" + json.dumps(payload, separators=(",", ":"))
    try:
        verdict, ms = await chat_json(_FREEZE_SYSTEM, user, client=client, max_tokens=300)
    except Exception:
        return None
    return {
        "decided_by": f"reasoner:{reasoner_model()}",
        "severity": _norm_sev(verdict.get("severity"), "high"),
        "likely_cause": str(verdict.get("likely_cause") or "unknown").strip()[:60],
        "rationale": str(verdict.get("rationale") or "").strip()[:400],
        "model": reasoner_model(),
        "latency_ms": ms,
    }

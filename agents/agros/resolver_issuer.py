"""
AGROS — bond-resolution orchestration.

Walks open predictive claims, checks each token's real live market, and settles
the bond only when the outcome is clear (rugged / held). When AGROS acts it
anchors its own resolution trace on Arc (agent 3) and calls
ClaimRegistry.resolve, after which winners can withdraw. Still-trading tokens are
left open — the honest result. Idempotent: resolve() is a no-op once a claim is
already resolved, and we skip non-open claims.
"""
from __future__ import annotations

from typing import Optional

import httpx

from agents.agros.resolver import assess_resolution, fetch_market
from shared.canonical import canonical_json, trace_hash

_AGROS_AGENT_ID = 3
_IPFS_GATEWAYS = ["https://ipfs.io/ipfs/", "https://cloudflare-ipfs.com/ipfs/"]
# AGROS only settles a real bond at or above this confidence; below it, stay open.
MIN_RESOLVE_CONFIDENCE = 0.7


def resolution_decision_id(claim_id: int) -> int:
    return 3_000_000_000 + int(claim_id)


async def _fetch_ipfs(cid: str, client: httpx.AsyncClient) -> Optional[dict]:
    if not cid:
        return None
    for gw in _IPFS_GATEWAYS:
        try:
            r = await client.get(gw + cid, timeout=8.0)
            if r.status_code == 200:
                return r.json()
        except (httpx.HTTPError, ValueError):
            continue
    return None


def _build_resolution_trace(claim: dict, nomos_summary: dict, assessment: dict, *, decision_id: int) -> dict:
    return {
        "schema_version": "akrita/trace/v1",
        "decision_id": decision_id,
        "agent_role": "agros",
        "decision_type": "bond_resolution",
        "fundamentals": {
            "claim_ref": {"claim_id": claim.get("claim_id"), "token_id": claim.get("token_id")},
            "token": nomos_summary.get("token"),
        },
        "technical": {
            "signal": "bond_resolution",
            "outcome": assessment.get("outcome"),
            "market": assessment.get("market", {}),
        },
        "conclusion": {
            "action": "resolve",
            "outcome": assessment.get("outcome"),
            "rugged": assessment.get("outcome") == "rugged",
            "statement": _statement(nomos_summary, assessment),
            "rationale": assessment.get("rationale"),
        },
        "reasoning": {
            "decided_by": assessment.get("decided_by"),
            "model": assessment.get("model"),
            "confidence": assessment.get("confidence"),
            "rationale": assessment.get("rationale"),
            "latency_ms": assessment.get("latency_ms"),
        },
    }


def _statement(nomos_summary: dict, assessment: dict) -> str:
    token = nomos_summary.get("token") or "the token"
    o = assessment.get("outcome")
    if o == "rugged":
        return f"AGROS resolved {token} RUGGED — the prediction paid out; the FOR side wins."
    if o == "held":
        return f"AGROS resolved {token} HELD — it survived the window; the AGAINST side wins."
    return f"AGROS held {token} open — still trading, insufficient evidence to settle."


async def resolve_open_claims(adapters, *, limit: int = 20) -> list[dict]:
    """Assess + (where clear) settle open predictive claims. Best-effort; one
    failure is captured, never raised."""
    cr = adapters.claim_registry
    out: list[dict] = []
    try:
        total = await cr.total_claims()
    except Exception as e:
        return [{"error": f"total_claims: {e}"}]
    stop = max(0, total - max(1, limit))
    async with httpx.AsyncClient(headers={"User-Agent": "akrita-agros"}) as client:
        for cid in range(total, stop, -1):
            try:
                claim = await cr.get_claim(cid)
                if not claim or claim.get("status") != "open" or int(claim.get("window_s", 0)) <= 0:
                    continue
                body = await _fetch_ipfs(claim.get("ipfs_cid", ""), client)
                src = ((body or {}).get("fundamentals") or {}).get("source") or {}
                addr = src.get("address")
                if not addr:
                    out.append({"claim_id": cid, "outcome": "open", "note": "no token address in trace"})
                    continue
                nomos_summary = {
                    "token": ((body or {}).get("fundamentals") or {}).get("token"),
                    "reasons": ((body or {}).get("technical") or {}).get("reasons", []),
                }
                market = await fetch_market(addr, client=client)
                assessment = await assess_resolution(claim, nomos_summary, market, client=client)
                assessment["market"] = market
                rec = {
                    "claim_id": cid,
                    "token": nomos_summary["token"],
                    "outcome": assessment["outcome"],
                    "confidence": assessment.get("confidence"),
                    "decided_by": assessment.get("decided_by"),
                    "rationale": assessment.get("rationale"),
                    "liquidity_usd": market.get("liquidity_usd"),
                }
                # Act only on a clear, confident rugged/held call.
                if assessment["outcome"] in ("rugged", "held") and assessment.get("confidence", 0) >= MIN_RESOLVE_CONFIDENCE:
                    rugged = assessment["outcome"] == "rugged"
                    decision_id = resolution_decision_id(cid)
                    trace = _build_resolution_trace(claim, nomos_summary, assessment, decision_id=decision_id)
                    thash = trace_hash(trace)
                    ipfs_cid = await adapters.nanopayment.pin_to_ipfs(canonical_json(trace))
                    await adapters.arc.commit_trace(_AGROS_AGENT_ID, decision_id, thash, ipfs_cid)
                    rcpt = await cr.resolve(cid, rugged)
                    rec["action"] = "resolved"
                    rec["rugged"] = rugged
                    rec["trace_hash"] = thash
                    rec["resolve_tx"] = getattr(rcpt, "tx_hash", None)
                else:
                    rec["action"] = "open"
                out.append(rec)
            except Exception as e:
                out.append({"claim_id": cid, "error": str(e)})
    return out

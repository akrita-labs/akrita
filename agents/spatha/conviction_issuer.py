"""
SPATHA — autonomous bond-conviction orchestration for the Rugpull Oracle.

For each predictive rug-risk claim NOMOS issued, SPATHA:
  1. reads NOMOS's IPFS-pinned reasoning (the on-chain-anchored trace body),
  2. forms its own LLM judgment — back / fade / abstain — a real second opinion,
  3. anchors THAT decision as a SPATHA trace on Arc (agent 2), and
  4. attempts the USDC bond stake (best-effort; gated on the SPATHA keeper holding
     USDC on Arc — when unfunded the decision still stands, execution is reported
     as gated).

Idempotent per claim: the SPATHA decision id is deterministic from the claim id,
so the trace commit dedups (no double-staking across restarts). Freeze
attestations (window 0, not predictive) are skipped — there is nothing to bet on.
"""
from __future__ import annotations

from typing import Optional

import httpx

from agents.spatha.bond_conviction import assess_conviction, conviction_plan
from agents.spatha.conviction_trace import build_conviction_trace, conviction_trace_hash
from shared.canonical import canonical_json

_SPATHA_AGENT_ID = 2
_IPFS_GATEWAYS = ["https://ipfs.io/ipfs/", "https://cloudflare-ipfs.com/ipfs/"]


def spatha_decision_id(claim_id: int) -> int:
    """Deterministic decision id so re-scans dedup on (agent 2, decisionId)."""
    return 2_000_000_000 + int(claim_id)


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


def _nomos_summary(body: Optional[dict], claim: dict) -> dict:
    body = body or {}
    f = body.get("fundamentals", {}) or {}
    t = body.get("technical", {}) or {}
    c = body.get("conclusion", {}) or {}
    r = body.get("reasoning", {}) or {}
    return {
        "claim_id": claim.get("claim_id"),
        "token": f.get("token") or t.get("token"),
        "severity": c.get("severity") or r.get("severity"),
        "nomos_confidence": c.get("confidence") if c.get("confidence") is not None else r.get("confidence"),
        "reasons": t.get("reasons", []),
        "nomos_rationale": c.get("rationale") or r.get("rationale"),
    }


async def decide_for_claim(adapters, claim: dict, *, max_stake_usdc: float) -> dict:
    """Run SPATHA's full conviction flow for one open predictive claim."""
    claim_id = int(claim["claim_id"])
    decision_id = spatha_decision_id(claim_id)

    # Idempotent: skip if SPATHA already anchored a decision for this claim.
    try:
        if await adapters.arc.get_trace_commit(_SPATHA_AGENT_ID, decision_id):
            return {"claim_id": claim_id, "already_decided": True}
    except Exception:
        pass

    async with httpx.AsyncClient(headers={"User-Agent": "akrita-spatha"}) as client:
        nomos_body = await _fetch_ipfs(claim.get("ipfs_cid", ""), client)
    summary = _nomos_summary(nomos_body, claim)

    conviction = await assess_conviction(summary)
    plan = conviction_plan(summary, conviction, max_stake_usdc=max_stake_usdc)

    # Attempt the on-chain stake (gated on USDC funding). Decision stands either way.
    if plan.get("action") == "stake":
        try:
            res = await adapters.claim_registry.stake(
                claim_id, bool(plan["backs_claim"]), int(plan["amount_base_units"])
            )
            plan["execution"] = "staked"
            plan["stake_tx"] = res.get("stake_tx")
        except Exception as e:
            plan["execution"] = f"gated: {type(e).__name__}"
    else:
        plan["execution"] = "abstained"

    # Anchor SPATHA's decision trace on Arc (agent 2) — real on-chain second opinion.
    body = build_conviction_trace(claim, summary, conviction, plan, decision_id=decision_id)
    hash_hex = conviction_trace_hash(body)
    cid = await adapters.nanopayment.pin_to_ipfs(canonical_json(body))
    anchor = await adapters.arc.commit_trace(_SPATHA_AGENT_ID, decision_id, hash_hex, cid)

    return {
        "claim_id": claim_id,
        "decided_by": conviction["decided_by"],
        "position": plan.get("position"),
        "conviction": conviction.get("conviction"),
        "amount_usdc": plan.get("amount_usdc", 0.0),
        "execution": plan.get("execution"),
        "rationale": conviction.get("rationale"),
        "decision_id": decision_id,
        "trace_hash": hash_hex,
        "ipfs_cid": cid,
        "arc_tx": getattr(anchor, "tx_hash", None),
    }


async def scan_open_claims(adapters, *, limit: int = 10, max_stake_usdc: float = 5.0) -> list[dict]:
    """Form (and where funded, place) SPATHA conviction on recent open, predictive
    claims. One failure is captured, never raised, so the loop can't stall."""
    cr = adapters.claim_registry
    out: list[dict] = []
    try:
        total = await cr.total_claims()
    except Exception as e:
        return [{"error": f"total_claims: {e}"}]
    stop = max(0, total - max(1, limit))
    for cid in range(total, stop, -1):
        try:
            claim = await cr.get_claim(cid)
            if not claim or claim.get("status") != "open":
                continue
            if int(claim.get("window_s", 0)) <= 0:  # freeze attestation, not predictive
                continue
            out.append(await decide_for_claim(adapters, claim, max_stake_usdc=max_stake_usdc))
        except Exception as e:
            out.append({"claim_id": cid, "error": str(e)})
    return out

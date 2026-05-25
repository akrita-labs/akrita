"""
NOMOS — rug-risk claim issuer (orchestration glue).

Ties the GoPlus signal to the chain: screen a token via GoPlus -> if it trips the
rug-risk rules, build the reasoning trace -> anchor it on Arc (TraceRegistry via
ArcReal) -> register the claim (ClaimRegistry). Pure helpers are import-safe; the
async issue flow drives the adapter container. End-to-end is live once
ClaimRegistry is deployed (CLAIM_REGISTRY_ADDR) and the keeper can sign.
"""
from __future__ import annotations

import time
from typing import Iterable, Optional

from agents.nomos.claim_trace import build_claim_trace, claim_trace_hash
from agents.nomos.freeze_watcher import (
    build_freeze_trace,
    fetch_freezes,
    fetch_freezes_etherscan,
    freeze_decision_id,
    freeze_trace_hash,
)
from agents.nomos.goplus_screen import build_claim_record, evaluate_risk, fetch_token_security
from agents.nomos.reasoner import apply_rules_floor, assess_freeze, assess_token
from shared.canonical import canonical_json
from shared.config import settings

_NOMOS_AGENT_ID = 1  # matches BuilderRegistry / TraceRegistry agent ids


def next_decision_id() -> int:
    """Monotonic-ish decision id (ms epoch) for TraceRegistry dedup."""
    return int(time.time() * 1000)


def goplus_decision_id(token_id: str) -> int:
    """Deterministic decision id from a token id, so the GoPlus screen loop is
    idempotent — re-screening the same token does not double-issue (the trace
    commit dedups on (agent, decisionId))."""
    return int(token_id.replace("0x", "")[:15], 16)


async def issue_for_token(
    adapters,
    address: str,
    chain_id: Optional[int] = None,
    *,
    decision_id: Optional[int] = None,
    window_s: Optional[int] = None,
    drop_threshold_bps: Optional[int] = None,
) -> dict:
    """Screen one token via GoPlus, then let NOMOS *decide*.

    The deterministic rules (`evaluate_risk`) supply a prior and the safe floor;
    the LLM reasoner makes the actual issue/skip call with a written rationale.
    A token the rules did not flag can only be issued at high conviction
    (`apply_rules_floor`). When NOMOS decides to issue, the reasoning is anchored
    on Arc BEFORE the claim is registered, so the attestation never post-dates the
    judgment. Tokens with no signal at all skip the reasoner (and the chain).
    """
    chain_id = chain_id if chain_id is not None else settings.goplus_chain_id
    window_s = window_s or settings.claim_window_s
    drop_threshold_bps = drop_threshold_bps or settings.claim_drop_threshold_bps

    rec = await fetch_token_security(address, chain_id)
    if not rec:
        return {"address": address.lower(), "flagged": False, "error": "goplus: no data"}
    risk = evaluate_risk(rec)

    # No strong indicator and no notable admin context → nothing to deliberate on;
    # cheap deterministic skip, no model call, no chain write.
    if not (risk["flagged"] or risk.get("context")):
        return {
            "address": address.lower(),
            "token": rec.get("token_symbol"),
            "flagged": False,
            "reasons": [],
            "decided_by": "deterministic",
        }

    record = build_claim_record(
        address, chain_id, rec, risk, window_s=window_s, drop_threshold_bps=drop_threshold_bps
    )

    # Idempotent per token: a deterministic decision id means the screen loop
    # re-screening the same token does not double-issue. Skip before spending the
    # reasoner call / chain write if this token is already attested.
    if decision_id is None:
        decision_id = goplus_decision_id(record["token_id"])
        try:
            if await adapters.arc.get_trace_commit(_NOMOS_AGENT_ID, decision_id):
                return {
                    "address": record["address"],
                    "token": record["token"],
                    "token_id": record["token_id"],
                    "flagged": True,
                    "already_attested": True,
                    "decision_id": decision_id,
                }
        except Exception:
            pass  # read failed -> fall through and let the write path decide

    assessment = await assess_token(record, risk)
    if not apply_rules_floor(assessment, risk):
        # NOMOS deliberately declined to accuse this token — return the reasoning
        # so the decision is inspectable even though nothing is written on-chain.
        return {
            "address": record["address"],
            "token": record["token"],
            "flagged": False,
            "skipped": True,
            "reasons": risk["reasons"],
            "decided_by": assessment["decided_by"],
            "confidence": assessment["confidence"],
            "severity": assessment["severity"],
            "rationale": assessment["rationale"],
        }

    decision_id = decision_id or next_decision_id()
    record["assessment"] = assessment
    body = build_claim_trace(record, decision_id=decision_id)
    hash_hex = claim_trace_hash(body)

    cid = await adapters.nanopayment.pin_to_ipfs(canonical_json(body))
    anchor = await adapters.arc.commit_trace(_NOMOS_AGENT_ID, decision_id, hash_hex, cid)
    issue = await adapters.claim_registry.issue_claim(
        record["token_id"],
        record["provenance"],  # already a 0x sha256 (bytes32)
        hash_hex,
        cid,
        window_s,
        drop_threshold_bps,
    )
    return {
        "token": record["token"],
        "address": record["address"],
        "token_id": record["token_id"],
        "flagged": True,
        "reasons": record["reasons"],
        "decided_by": assessment["decided_by"],
        "confidence": assessment["confidence"],
        "severity": assessment["severity"],
        "rationale": assessment["rationale"],
        "decision_id": decision_id,
        "trace_hash": hash_hex,
        "ipfs_cid": cid,
        "arc_tx": getattr(anchor, "tx_hash", None),
        "claim_tx": getattr(issue, "tx_hash", None),
    }


async def screen_watchlist(
    adapters,
    tokens: Iterable[str],
    *,
    chain_id: Optional[int] = None,
) -> list[dict]:
    """Screen a list of token addresses; issue claims for the flagged ones.
    One bad token is captured, never raised, so it can't stall the screen."""
    out: list[dict] = []
    for addr in tokens:
        try:
            out.append(await issue_for_token(adapters, addr, chain_id))
        except Exception as e:
            out.append({"address": str(addr).lower(), "error": str(e)})
    return out


async def discover_and_screen(
    adapters,
    *,
    max_candidates: int = 40,
    max_select: int = 5,
) -> dict:
    """Goal-seeking: NOMOS discovers freshly-promoted tokens from the open market,
    the reasoner triages which are worth investigating, and each selected target is
    screened + (if a genuine rug) claimed — picking its own targets end to end."""
    from agents.nomos.discovery import fetch_candidates, triage

    candidates = await fetch_candidates(limit=max_candidates)
    plan = await triage(candidates, max_select=max_select)
    results: list[dict] = []
    for c in plan.get("selected", []):
        try:
            r = await issue_for_token(adapters, c["address"], c.get("chain_id"))
            r["triage_reason"] = c.get("triage_reason")
            r["chain"] = c.get("chain")
            results.append(r)
        except Exception as e:
            results.append({"address": c.get("address"), "error": str(e)})
    return {
        "discovered": len(candidates),
        "considered": plan.get("considered", 0),
        "triaged_by": plan.get("decided_by"),
        "triage_rationale": plan.get("rationale"),
        "screened": len(results),
        "results": results,
    }


# ----- on-chain stablecoin freeze attestations (primary signal) -------------


async def issue_for_freeze(adapters, rec: dict, *, decision_id: Optional[int] = None) -> dict:
    """Anchor one freeze event as a signed on-chain attestation: trace -> IPFS ->
    TraceRegistry -> ClaimRegistry (window/threshold 0 — it's an attestation, no
    drop-prediction bond). `decision_id` is deterministic from the freeze tx, so
    re-issuing the same freeze is a no-op (the trace commit dedups)."""
    decision_id = decision_id or freeze_decision_id(rec["freeze_tx"])
    # Skip if already attested — a cheap read avoids a guaranteed-revert on-chain
    # write (the trace commit dedups on (agent, decisionId)). Keeps the loop idle-cheap.
    try:
        if await adapters.arc.get_trace_commit(_NOMOS_AGENT_ID, decision_id):
            return {
                "frozen_address": rec["frozen_address"],
                "issuer": rec["issuer"],
                "already_attested": True,
            }
    except Exception:
        pass  # read failed -> fall through and let the write path decide

    # NOMOS interprets the freeze (severity / likely cause / rationale) before
    # anchoring. Best-effort: the on-chain fact is attested regardless of the model.
    assessment = await assess_freeze(rec)
    body = build_freeze_trace(rec, decision_id=decision_id, assessment=assessment)
    hash_hex = freeze_trace_hash(body)

    cid = await adapters.nanopayment.pin_to_ipfs(canonical_json(body))
    anchor = await adapters.arc.commit_trace(_NOMOS_AGENT_ID, decision_id, hash_hex, cid)
    issue = await adapters.claim_registry.issue_claim(
        rec["token_id"], rec["freeze_tx"], hash_hex, cid, 0, 0
    )
    out = {
        "frozen_address": rec["frozen_address"],
        "issuer": rec["issuer"],
        "token_id": rec["token_id"],
        "decision_id": decision_id,
        "trace_hash": hash_hex,
        "ipfs_cid": cid,
        "arc_tx": getattr(anchor, "tx_hash", None),
        "claim_tx": getattr(issue, "tx_hash", None),
    }
    if assessment:
        out["decided_by"] = assessment["decided_by"]
        out["severity"] = assessment["severity"]
        out["likely_cause"] = assessment["likely_cause"]
        out["rationale"] = assessment["rationale"]
    return out


async def scan_freezes(adapters, *, limit: Optional[int] = None, deep: bool = False) -> list[dict]:
    """Read recent USDT/USDC freezes and attest each on Arc. Idempotent per
    freeze; one failure is captured, never raised. `deep=True` uses Etherscan
    (when ETHERSCAN_API_KEY is set) for full history instead of the RPC window."""
    if deep and settings.etherscan_api_key:
        recs = await fetch_freezes_etherscan(settings.etherscan_api_key, from_block=0)
    else:
        recs = await fetch_freezes(settings.eth_rpc_url, lookback_blocks=settings.freeze_lookback_blocks)
    if limit:
        recs = recs[:limit]
    out: list[dict] = []
    for r in recs:
        try:
            out.append(await issue_for_freeze(adapters, r))
        except Exception as e:
            out.append({"frozen_address": r.get("frozen_address"), "error": str(e)})
    return out

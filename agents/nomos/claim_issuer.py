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
from agents.nomos.goplus_screen import build_claim_record, evaluate_risk, fetch_token_security
from shared.canonical import canonical_json
from shared.config import settings

_NOMOS_AGENT_ID = 1  # matches BuilderRegistry / TraceRegistry agent ids


def next_decision_id() -> int:
    """Monotonic-ish decision id (ms epoch) for TraceRegistry dedup."""
    return int(time.time() * 1000)


async def issue_for_token(
    adapters,
    address: str,
    chain_id: Optional[int] = None,
    *,
    decision_id: Optional[int] = None,
    window_s: Optional[int] = None,
    drop_threshold_bps: Optional[int] = None,
) -> dict:
    """Screen one token via GoPlus; if flagged, issue a signed rug-risk claim
    end-to-end and return a summary. Unflagged tokens return `{flagged: False}`
    without touching the chain. The trace is anchored on Arc BEFORE the claim is
    registered, so the on-chain attestation never post-dates the claim.
    """
    chain_id = chain_id if chain_id is not None else settings.goplus_chain_id
    window_s = window_s or settings.claim_window_s
    drop_threshold_bps = drop_threshold_bps or settings.claim_drop_threshold_bps

    rec = await fetch_token_security(address, chain_id)
    if not rec:
        return {"address": address.lower(), "flagged": False, "error": "goplus: no data"}
    risk = evaluate_risk(rec)
    if not risk["flagged"]:
        return {
            "address": address.lower(),
            "token": rec.get("token_symbol"),
            "flagged": False,
            "reasons": [],
        }

    decision_id = decision_id or next_decision_id()
    record = build_claim_record(
        address, chain_id, rec, risk, window_s=window_s, drop_threshold_bps=drop_threshold_bps
    )
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

"""
NOMOS — rug-risk claim issuer (orchestration glue).

Ties the pieces together: an NFI blacklist addition -> reasoning trace -> anchor
on Arc (TraceRegistry via ArcReal) -> register the claim (ClaimRegistry). Pure
helpers (credibility, decision id, bytes32 packing) are import-safe; the async
issue flow drives the adapter container. End-to-end is unverified until
ClaimRegistry is deployed (CLAIM_REGISTRY_ADDR) and the keeper can sign.
"""
from __future__ import annotations

import time
from typing import Optional

from agents.nomos.claim_trace import build_claim_trace, claim_trace_hash
from agents.nomos.nfi_watcher import build_claim_record, diff_additions, fetch_blacklist
from shared.canonical import canonical_json
from shared.config import settings

_NOMOS_AGENT_ID = 1  # matches BuilderRegistry / TraceRegistry agent ids


def source_commit_b32(commit: str) -> str:
    """Pack a git commit sha (40 hex) into a 0x bytes32 hex (left-padded)."""
    h = (commit or "").replace("0x", "")[:64]
    return "0x" + h.rjust(64, "0")


def credibility_for(record: dict) -> float:
    """NOMOS's read on rug risk from the NFI signal, bounded [0,1].

    NFI is a reputable, actively-maintained source, so a blacklist addition is a
    strong prior. A deliberate placeholder for later on-chain features (liquidity,
    token age, holder concentration) — recorded in the trace, not yet a gate.
    """
    return 0.85


def next_decision_id() -> int:
    """Monotonic-ish decision id (ms epoch) for TraceRegistry dedup."""
    return int(time.time() * 1000)


async def issue_for_addition(
    adapters,
    pair: str,
    exchange: str,
    source_commit: str,
    *,
    decision_id: Optional[int] = None,
    window_s: Optional[int] = None,
    drop_threshold_bps: Optional[int] = None,
) -> dict:
    """Issue one signed rug-risk claim end-to-end and return a summary.

    Order matters: the trace is anchored on Arc BEFORE the claim is registered,
    so the on-chain attestation always predates (or coincides with) the claim.
    """
    window_s = window_s or settings.claim_window_s
    drop_threshold_bps = drop_threshold_bps or settings.claim_drop_threshold_bps
    decision_id = decision_id or next_decision_id()

    record = build_claim_record(
        pair, exchange, source_commit, window_s=window_s, drop_threshold_bps=drop_threshold_bps
    )
    credibility = credibility_for(record)
    body = build_claim_trace(record, credibility=credibility, decision_id=decision_id)
    hash_hex = claim_trace_hash(body)

    cid = await adapters.nanopayment.pin_to_ipfs(canonical_json(body))
    anchor = await adapters.arc.commit_trace(_NOMOS_AGENT_ID, decision_id, hash_hex, cid)
    issue = await adapters.claim_registry.issue_claim(
        record["token_id"],
        source_commit_b32(source_commit),
        hash_hex,
        cid,
        window_s,
        drop_threshold_bps,
    )
    return {
        "token": record["token"],
        "token_id": record["token_id"],
        "decision_id": decision_id,
        "trace_hash": hash_hex,
        "ipfs_cid": cid,
        "arc_tx": getattr(anchor, "tx_hash", None),
        "claim_tx": getattr(issue, "tx_hash", None),
        "credibility": credibility,
    }


async def run_once(
    adapters,
    last_seen: set[str],
    *,
    exchange: Optional[str] = None,
) -> tuple[list[dict], set[str]]:
    """Poll the NFI blacklist once; issue a claim per *new* addition.

    Returns (issued_summaries, updated_seen). On a cold start (`last_seen` empty)
    this seeds the baseline without issuing, so a continuous loop doesn't backfill
    the entire existing blacklist as "new". A bad single claim is captured, never
    raised, so one failure can't stall the loop.
    """
    exchange = exchange or settings.nfi_blacklist_exchange
    pairs, commit = await fetch_blacklist(exchange, repo=settings.nfi_repo)
    additions = diff_additions(last_seen, pairs) if last_seen else []
    issued: list[dict] = []
    for pair in additions:
        try:
            issued.append(await issue_for_addition(adapters, pair, exchange, commit))
        except Exception as e:
            issued.append({"pair": pair, "error": str(e)})
    return issued, pairs

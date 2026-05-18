"""Trace viewer endpoints.

GET /traces/{decision_id}     — fetch trace metadata by decision ID
GET /traces/by-hash/{hash}    — fetch trace metadata by sha256 hash
GET /traces/{decision_id}/body — fetch full IPFS body + verify hash matches
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from adapters import get_adapters
from orchestrator.app.state import state
from shared.canonical import sha256_hex

router = APIRouter()


@router.get("/{decision_id}")
async def get_trace(decision_id: int) -> dict:
    trace = await state.get_trace(decision_id)
    if not trace:
        raise HTTPException(404, "trace not found")
    return trace


@router.get("/by-hash/{trace_hash}")
async def get_trace_by_hash(trace_hash: str) -> dict:
    if not trace_hash.startswith("0x"):
        trace_hash = "0x" + trace_hash
    trace = await state.get_trace_by_hash(trace_hash)
    if not trace:
        raise HTTPException(404, "trace not found")
    return trace


@router.get("/{decision_id}/verify")
async def verify_trace(decision_id: int) -> dict:
    """Fetch the IPFS body, recompute sha256, confirm it matches the on-chain hash."""
    trace = await state.get_trace(decision_id)
    if not trace:
        raise HTTPException(404, "trace not found")

    adapters = get_adapters()
    # Mock nanopayment has a _fetch helper; real impl would fetch from IPFS HTTP gw
    from adapters.mock.circle import MockNanopayment
    if not isinstance(adapters.nanopayment, MockNanopayment):
        raise HTTPException(501, "live IPFS verification not yet wired")

    body_bytes = adapters.nanopayment._fetch(trace["ipfs_cid"])
    if body_bytes is None:
        raise HTTPException(502, "IPFS body unavailable")

    recomputed = sha256_hex(body_bytes)
    matches = recomputed == trace["trace_hash"]

    return {
        "decision_id": decision_id,
        "on_chain_hash": trace["trace_hash"],
        "recomputed_hash": recomputed,
        "matches": matches,
        "body_size_bytes": len(body_bytes),
        "ipfs_cid": trace["ipfs_cid"],
        "arc_tx_hash": trace["arc_tx_hash"],
        "arc_block": trace["arc_block"],
    }


@router.get("/{decision_id}/body")
async def get_trace_body(decision_id: int) -> dict:
    """Return the actual reasoning content (decoded from IPFS)."""
    import json
    trace = await state.get_trace(decision_id)
    if not trace:
        raise HTTPException(404, "trace not found")

    adapters = get_adapters()
    from adapters.mock.circle import MockNanopayment
    if not isinstance(adapters.nanopayment, MockNanopayment):
        raise HTTPException(501, "live IPFS fetch not yet wired")

    body_bytes = adapters.nanopayment._fetch(trace["ipfs_cid"])
    if body_bytes is None:
        raise HTTPException(502, "IPFS body unavailable")

    return json.loads(body_bytes)

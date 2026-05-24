"""Rugpull Oracle — claim endpoints (read-only).

GET /api/claims        — list issued rug-risk claims (newest first) + bond pools
GET /api/claims/{id}   — one claim + its bond pool

Degrades gracefully: if CLAIM_REGISTRY_ADDR isn't set / deployed yet, the list
returns `available: false` rather than erroring (honest "not live yet" state).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from adapters import get_adapters

router = APIRouter()


class IssueClaimReq(BaseModel):
    token_address: str  # ERC-20 contract address to screen via GoPlus
    chain_id: int | None = None  # defaults to settings.goplus_chain_id


class ResolveReq(BaseModel):
    rugged: bool


async def _with_bond(cr, claim: dict, claim_id: int) -> dict:
    try:
        claim["bond"] = await cr.get_bond(claim_id)
    except Exception:
        claim["bond"] = {"for_stake": 0, "against_stake": 0}
    return claim


@router.get("")
async def list_claims(limit: int = 50) -> dict:
    cr = get_adapters().claim_registry
    try:
        total = await cr.total_claims()
    except Exception as e:
        return {"claims": [], "total": 0, "available": False, "detail": str(e)}

    out: list[dict] = []
    stop = max(0, total - max(1, limit))
    for cid in range(total, stop, -1):
        c = await cr.get_claim(cid)
        if c:
            out.append(await _with_bond(cr, c, cid))
    return {"claims": out, "total": total, "available": True}


@router.get("/{claim_id}")
async def get_claim(claim_id: int) -> dict:
    cr = get_adapters().claim_registry
    c = await cr.get_claim(claim_id)
    if not c:
        raise HTTPException(404, "claim not found")
    return await _with_bond(cr, c, claim_id)


@router.post("/issue")
async def issue_claim(req: IssueClaimReq) -> dict:
    """Operator/demo: screen a token via GoPlus and, if flagged, issue a signed
    rug-risk claim end-to-end (trace -> anchor -> register). Unflagged tokens
    return flagged:false without touching the chain. 503 if the oracle isn't
    wired (keepers + deployed registry)."""
    from agents.nomos.claim_issuer import issue_for_token

    try:
        return await issue_for_token(get_adapters(), req.token_address, req.chain_id)
    except Exception as e:
        raise HTTPException(503, f"oracle not ready: {e}")


@router.post("/{claim_id}/resolve")
async def resolve_claim(claim_id: int, req: ResolveReq) -> dict:
    """Resolver-gated: record whether the token rugged within the window."""
    try:
        rcpt = await get_adapters().claim_registry.resolve(claim_id, req.rugged)
    except Exception as e:
        raise HTTPException(503, f"resolve failed: {e}")
    return {"claim_id": claim_id, "rugged": req.rugged, "tx_hash": getattr(rcpt, "tx_hash", None)}

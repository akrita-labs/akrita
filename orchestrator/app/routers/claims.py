"""Rugpull Oracle — claim endpoints (read-only).

GET /api/claims        — list issued rug-risk claims (newest first) + bond pools
GET /api/claims/{id}   — one claim + its bond pool

Degrades gracefully: if CLAIM_REGISTRY_ADDR isn't set / deployed yet, the list
returns `available: false` rather than erroring (honest "not live yet" state).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from adapters import get_adapters

router = APIRouter()


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

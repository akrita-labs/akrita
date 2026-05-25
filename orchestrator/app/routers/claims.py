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
from shared.config import settings

router = APIRouter()


async def _with_spatha(arc, claim: dict, claim_id: int) -> dict:
    """Attach SPATHA's on-chain conviction trace (agent 2) for predictive claims,
    so the oracle UI can show the second-opinion decision next to the claim."""
    if int(claim.get("window_s", 0)) <= 0:
        return claim  # freeze attestation — not predictive, no SPATHA bet
    from agents.spatha.conviction_issuer import spatha_decision_id

    try:
        commit = await arc.get_trace_commit(2, spatha_decision_id(claim_id))
    except Exception:
        commit = None
    if commit and commit.get("ipfs_cid"):
        claim["spatha"] = {"trace_hash": commit.get("trace_hash"), "ipfs_cid": commit.get("ipfs_cid")}
    return claim


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

    arc = get_adapters().arc
    out: list[dict] = []
    stop = max(0, total - max(1, limit))
    for cid in range(total, stop, -1):
        c = await cr.get_claim(cid)
        if c:
            c = await _with_bond(cr, c, cid)
            c = await _with_spatha(arc, c, cid)
            out.append(c)
    return {"claims": out, "total": total, "available": True}


@router.get("/{claim_id}")
async def get_claim(claim_id: int) -> dict:
    cr = get_adapters().claim_registry
    c = await cr.get_claim(claim_id)
    if not c:
        raise HTTPException(404, "claim not found")
    c = await _with_bond(cr, c, claim_id)
    return await _with_spatha(get_adapters().arc, c, claim_id)


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


@router.post("/scan-freezes")
async def scan_freezes(limit: int = 5, deep: bool = False) -> dict:
    """Operator/demo: read recent on-chain USDT/USDC freezes and attest each on
    Arc (idempotent). `deep=true` backfills full history via Etherscan (needs
    ETHERSCAN_API_KEY). 503 until the oracle is wired (keepers + deployed registry)."""
    from agents.nomos.claim_issuer import scan_freezes as _scan

    try:
        results = await _scan(get_adapters(), limit=max(1, limit), deep=deep)
        return {"scanned": len(results), "results": results}
    except Exception as e:
        raise HTTPException(503, f"freeze scan failed: {e}")


@router.post("/discover")
async def discover(max_candidates: int = 40, max_select: int = 5) -> dict:
    """Operator/demo: NOMOS discovers freshly-promoted tokens from the open market,
    the reasoner triages which to screen, and genuine rugs are claimed on-chain —
    the agent picking its own targets. 503 until the oracle is wired."""
    from agents.nomos.claim_issuer import discover_and_screen

    try:
        return await discover_and_screen(
            get_adapters(), max_candidates=max(1, max_candidates), max_select=max(1, max_select)
        )
    except Exception as e:
        raise HTTPException(503, f"discovery failed: {e}")


@router.post("/resolve-scan")
async def resolve_scan(limit: int = 20) -> dict:
    """Operator/demo: AGROS checks each open predictive claim's real live market and
    settles the bond only on clear evidence (rugged/held); still-trading tokens stay
    open. Returns the per-claim assessment. 503 until the oracle is wired."""
    from agents.agros.resolver_issuer import resolve_open_claims

    try:
        results = await resolve_open_claims(get_adapters(), limit=max(1, limit))
        return {"scanned": len(results), "results": results}
    except Exception as e:
        raise HTTPException(503, f"resolve scan failed: {e}")


@router.post("/spatha-scan")
async def spatha_scan(limit: int = 10) -> dict:
    """Operator/demo: SPATHA forms (and where funded, places) bond conviction on
    recent open predictive claims, anchoring each decision on Arc as agent 2.
    Idempotent per claim. 503 until the oracle is wired."""
    from agents.spatha.conviction_issuer import scan_open_claims

    try:
        results = await scan_open_claims(
            get_adapters(), limit=max(1, limit), max_stake_usdc=settings.spatha_max_stake_usdc
        )
        return {"scanned": len(results), "results": results}
    except Exception as e:
        raise HTTPException(503, f"spatha scan failed: {e}")


@router.post("/{claim_id}/resolve")
async def resolve_claim(claim_id: int, req: ResolveReq) -> dict:
    """Resolver-gated: record whether the token rugged within the window."""
    try:
        rcpt = await get_adapters().claim_registry.resolve(claim_id, req.rugged)
    except Exception as e:
        raise HTTPException(503, f"resolve failed: {e}")
    return {"claim_id": claim_id, "rugged": req.rugged, "tx_hash": getattr(rcpt, "tx_hash", None)}

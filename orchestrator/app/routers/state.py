"""Read-only state endpoints — used by agents and UI."""
from __future__ import annotations

import time

from fastapi import APIRouter

from adapters import get_adapters
from orchestrator.app.state import state

router = APIRouter()


@router.get("/inventory")
async def get_all_inventory() -> dict:
    snapshots = await state.all_inventory()
    return {
        "ts_ms": int(time.time() * 1000),
        "inventory": [s.model_dump(mode="json") for s in snapshots],
    }


@router.get("/inventory/{market_id}")
async def get_inventory_market(market_id: str) -> dict:
    inv = await state.get_inventory(market_id)
    return inv.model_dump(mode="json")


@router.get("/balances")
async def get_balances() -> dict:
    adapters = get_adapters()
    wallets = adapters.wallets
    out: dict = {}

    # Legacy agent-facing alias -> (role, {short_chain: circle_blockchain}).
    roles = {
        "nomos-keeper": "pricing",
        "spatha-keeper": "hedge",
        "agros-keeper": "treasury",
        "trace-keeper": "trace",
    }
    chains = {"arc": "ARC-TESTNET", "polygon": "MATIC-AMOY"}

    for alias, role in roles.items():
        out[alias] = {}
        for short, circle_chain in chains.items():
            try:
                wid = wallets.wallet_id(role, circle_chain)
                out[alias][short] = await wallets.get_balance(wid, circle_chain)
            except Exception:
                pass

    # Circle doesn't track USYC; read it directly from the token via USYCReal.
    try:
        treasury_wid = wallets.wallet_id("treasury", "ARC-TESTNET")
        usyc_bal = await adapters.usyc.get_balance(treasury_wid)
        out.setdefault("agros-keeper", {}).setdefault("arc", {})["USYC"] = usyc_bal
    except Exception:
        pass

    out["usyc_apy"] = await adapters.usyc.get_current_yield_apy()
    out["usyc_nav"] = await adapters.usyc.get_nav_per_share()
    return out


@router.get("/traces")
async def get_traces(limit: int = 20) -> dict:
    """Committed traces straight from the traces table (the on-chain anchor
    record), independent of whether the decision's execution succeeded."""
    return {
        "count": await state.count_traces(),
        "traces": await state.list_recent_traces(limit=limit),
    }


@router.get("/fills")
async def get_fills(limit: int = 20) -> dict:
    fills = await state.list_fills(limit=limit)
    return {
        "ts_ms": int(time.time() * 1000),
        "fills": fills,
        "cumulative_builder_fees_usdc": await state.cumulative_builder_fees_usdc(),
    }


@router.get("/decisions")
async def get_decisions(limit: int = 20) -> dict:
    decisions = await state.list_recent_decisions(limit=limit)
    return {"decisions": decisions}


@router.get("/treasury")
async def get_treasury(limit: int = 20) -> dict:
    actions = await state.list_treasury(limit=limit)
    return {"actions": actions}


@router.get("/hedges")
async def get_hedges() -> dict:
    return {"open_positions": await state.list_open_hedges()}

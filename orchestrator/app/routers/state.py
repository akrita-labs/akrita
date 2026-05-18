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
    out = {}
    for wallet in ["nomos-keeper", "spatha-keeper", "agros-keeper", "trace-keeper"]:
        out[wallet] = {}
        for chain in ["arc", "polygon", "hyperliquid"]:
            try:
                bal = await adapters.wallets.get_balance(wallet, chain)
                out[wallet][chain] = bal
            except Exception:
                pass
    out["usyc_apy"] = await adapters.usyc.get_current_yield_apy()
    out["usyc_nav"] = await adapters.usyc.get_nav_per_share()
    return out


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

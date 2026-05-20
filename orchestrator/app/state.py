"""
AKRITA state facade.

This module preserves the legacy `state.X(...)` async interface that routers
and the trace pipeline already use. Under the hood every call now opens
a short-lived session against Postgres (via the repositories) or talks
to Redis (counters + nonces). The only thing that remains in-process
is the WebSocket fan-out — Postgres + Redis are durable, but live UI
subscriptions are by definition per-process.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from orchestrator.app.db.session import async_session_factory
from orchestrator.app.redis_client import (
    claim_nonce as _redis_claim_nonce,
    next_decision_id as _redis_next_decision_id,
)
from orchestrator.app.repositories import (
    SQLDecisionRepo,
    SQLFillRepo,
    SQLHedgePositionRepo,
    SQLInventoryRepo,
    SQLTraceRepo,
    SQLTreasuryActionRepo,
)
from shared.models import InventorySnapshot


class StateStore:
    def __init__(self) -> None:
        self._ws_subscribers: list[asyncio.Queue] = []

    # ----- Decision IDs ----------------------------------------------------

    async def next_decision_id(self, agent_role: str) -> int:
        return await _redis_next_decision_id(agent_role)

    # ----- Nonce replay protection ----------------------------------------

    async def claim_nonce(self, agent_role: str, nonce: int) -> bool:
        return await _redis_claim_nonce(agent_role, nonce)

    # ----- Decision persistence -------------------------------------------

    async def store_decision(self, decision_dict: dict) -> None:
        async with async_session_factory()() as session:
            await SQLDecisionRepo(session).store(decision_dict)
            await session.commit()

    async def get_decision(
        self, decision_id: int, agent_role: Optional[str] = None
    ) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLDecisionRepo(session).get(decision_id, agent_role)

    async def list_recent_decisions(self, limit: int = 20) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLDecisionRepo(session).list_recent(limit)

    # ----- Trace commits ---------------------------------------------------

    async def store_trace(self, decision_id: int, trace_info: dict) -> None:
        agent_role = trace_info.get("agent_role", "?")
        async with async_session_factory()() as session:
            await SQLTraceRepo(session).store(decision_id, agent_role, trace_info)
            await session.commit()

    async def get_trace(self, decision_id: int) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLTraceRepo(session).get(decision_id)

    async def get_trace_by_hash(self, trace_hash: str) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLTraceRepo(session).get_by_hash(trace_hash)

    # ----- Inventory -------------------------------------------------------

    async def update_inventory(self, snapshot: InventorySnapshot) -> None:
        async with async_session_factory()() as session:
            await SQLInventoryRepo(session).append(snapshot)
            await session.commit()

    async def get_inventory(self, market_id: str) -> InventorySnapshot:
        async with async_session_factory()() as session:
            return await SQLInventoryRepo(session).get_latest(market_id)

    async def all_inventory(self) -> list[InventorySnapshot]:
        async with async_session_factory()() as session:
            return await SQLInventoryRepo(session).list_latest_all()

    # ----- Fills -----------------------------------------------------------

    async def record_fill(self, fill_dict: dict) -> None:
        async with async_session_factory()() as session:
            inserted = await SQLFillRepo(session).record(fill_dict)
            if inserted:
                # Mirror the legacy behaviour: derive a fresh inventory snapshot.
                inv_repo = SQLInventoryRepo(session)
                inv = await inv_repo.get_latest(fill_dict["market_id"])
                delta = float(fill_dict.get("size", 0.0))
                if fill_dict.get("side") == "BUY":
                    inv = InventorySnapshot(
                        market_id=inv.market_id,
                        net_exposure=inv.net_exposure + delta,
                        long_size=inv.long_size + delta,
                        short_size=inv.short_size,
                        snapshot_ts_ms=int(time.time() * 1000),
                    )
                else:
                    inv = InventorySnapshot(
                        market_id=inv.market_id,
                        net_exposure=inv.net_exposure - delta,
                        long_size=inv.long_size,
                        short_size=inv.short_size + delta,
                        snapshot_ts_ms=int(time.time() * 1000),
                    )
                await inv_repo.append(inv)
            await session.commit()

    async def list_fills(self, limit: int = 50) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLFillRepo(session).list_recent(limit)

    async def cumulative_builder_fees_usdc(self) -> float:
        async with async_session_factory()() as session:
            return await SQLFillRepo(session).cumulative_builder_fees_usdc()

    # ----- Hedge positions -------------------------------------------------

    async def record_hedge(self, position_dict: dict) -> None:
        async with async_session_factory()() as session:
            await SQLHedgePositionRepo(session).upsert(position_dict)
            await session.commit()

    async def list_open_hedges(self) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLHedgePositionRepo(session).list_open()

    # ----- Treasury actions ------------------------------------------------

    async def record_treasury(self, action_dict: dict) -> None:
        async with async_session_factory()() as session:
            await SQLTreasuryActionRepo(session).record(action_dict)
            await session.commit()

    async def list_treasury(self, limit: int = 50) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLTreasuryActionRepo(session).list_recent(limit)

    # ----- WebSocket fanout (process-local) -------------------------------

    def subscribe_ws(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._ws_subscribers.append(q)
        return q

    def unsubscribe_ws(self, q: asyncio.Queue) -> None:
        if q in self._ws_subscribers:
            self._ws_subscribers.remove(q)

    async def broadcast(self, event: dict) -> None:
        for q in self._ws_subscribers:
            if not q.full():
                await q.put(event)


# Process-wide singleton (preserved for backwards compatibility).
state = StateStore()

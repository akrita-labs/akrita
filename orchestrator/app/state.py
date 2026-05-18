"""
AKRITA in-memory state store.

For the prototype, all persistent state lives here. In real deployment,
this becomes Postgres + Redis (see docs/INTEGRATION.md).

This module is intentionally simple. The point is that all state
access goes through a typed interface, so the swap to Postgres later
is a single-file change.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Optional

from shared.models import (
    InventorySnapshot,
)


class StateStore:
    def __init__(self):
        # decision_id -> decision payload
        self._decisions: dict[int, dict] = {}
        # nonces seen (replay protection)
        self._nonces: set[tuple[str, int]] = set()
        # decision_id -> trace commit info
        self._traces: dict[int, dict] = {}
        # market_id -> inventory snapshot (latest only — full series would be Postgres)
        self._inventory: dict[str, InventorySnapshot] = {}
        # fills log
        self._fills: list[dict] = []
        # hedge positions
        self._hedge_positions: dict[int, dict] = {}
        # treasury actions log
        self._treasury_actions: list[dict] = []
        # next monotonic decision ID per role
        self._decision_counter: dict[str, int] = defaultdict(lambda: 0)

        self._lock = asyncio.Lock()

        # WebSocket fanout
        self._ws_subscribers: list[asyncio.Queue] = []

    # ----- Decision IDs ----------------------------------------------------

    async def next_decision_id(self, agent_role: str) -> int:
        async with self._lock:
            self._decision_counter[agent_role] += 1
            return self._decision_counter[agent_role]

    # ----- Nonce replay protection ----------------------------------------

    async def claim_nonce(self, agent_role: str, nonce: int) -> bool:
        """Returns True if nonce was unused (now claimed), False if duplicate."""
        async with self._lock:
            key = (agent_role, nonce)
            if key in self._nonces:
                return False
            self._nonces.add(key)
            return True

    # ----- Decision persistence -------------------------------------------

    async def store_decision(self, decision_dict: dict) -> None:
        async with self._lock:
            key = (decision_dict.get("agent_role", "?"), decision_dict["decision_id"])
            self._decisions[key] = decision_dict

    async def get_decision(self, decision_id: int, agent_role: str | None = None) -> Optional[dict]:
        if agent_role is not None:
            return self._decisions.get((agent_role, decision_id))
        # No role specified — return the first matching record found
        for (role, did), d in self._decisions.items():
            if did == decision_id:
                return d
        return None

    async def list_recent_decisions(self, limit: int = 20) -> list[dict]:
        async with self._lock:
            recent = sorted(
                self._decisions.values(),
                key=lambda d: d.get("ts_ms", 0),
                reverse=True,
            )[:limit]
            return recent

    # ----- Trace commits ---------------------------------------------------

    async def store_trace(self, decision_id: int, trace_info: dict) -> None:
        async with self._lock:
            self._traces[decision_id] = trace_info

    async def get_trace(self, decision_id: int) -> Optional[dict]:
        return self._traces.get(decision_id)

    async def get_trace_by_hash(self, trace_hash: str) -> Optional[dict]:
        for t in self._traces.values():
            if t.get("trace_hash") == trace_hash:
                return t
        return None

    # ----- Inventory -------------------------------------------------------

    async def update_inventory(self, snapshot: InventorySnapshot) -> None:
        async with self._lock:
            self._inventory[snapshot.market_id] = snapshot

    async def get_inventory(self, market_id: str) -> InventorySnapshot:
        if market_id in self._inventory:
            return self._inventory[market_id]
        return InventorySnapshot(
            market_id=market_id,
            net_exposure=0.0,
            long_size=0.0,
            short_size=0.0,
            snapshot_ts_ms=int(time.time() * 1000),
        )

    async def all_inventory(self) -> list[InventorySnapshot]:
        return list(self._inventory.values())

    # ----- Fills -----------------------------------------------------------

    async def record_fill(self, fill_dict: dict) -> None:
        async with self._lock:
            self._fills.append(fill_dict)
            # Update inventory from fill
            mid = fill_dict["market_id"]
            inv = self._inventory.get(mid) or InventorySnapshot(
                market_id=mid, net_exposure=0.0, long_size=0.0,
                short_size=0.0, snapshot_ts_ms=int(time.time() * 1000),
            )
            delta = fill_dict["size"]
            if fill_dict["side"] == "BUY":
                inv.long_size += delta
                inv.net_exposure += delta
            else:
                inv.short_size += delta
                inv.net_exposure -= delta
            inv.snapshot_ts_ms = int(time.time() * 1000)
            self._inventory[mid] = inv

    async def list_fills(self, limit: int = 50) -> list[dict]:
        return list(reversed(self._fills[-limit:]))

    async def cumulative_builder_fees_usdc(self) -> float:
        return sum(f.get("builder_fee_usdc", 0.0) for f in self._fills)

    # ----- Hedge positions -------------------------------------------------

    async def record_hedge(self, position_dict: dict) -> None:
        async with self._lock:
            self._hedge_positions[position_dict["position_id"]] = position_dict

    async def list_open_hedges(self) -> list[dict]:
        return [p for p in self._hedge_positions.values() if p.get("status") == "open"]

    # ----- Treasury actions ------------------------------------------------

    async def record_treasury(self, action_dict: dict) -> None:
        async with self._lock:
            self._treasury_actions.append(action_dict)

    async def list_treasury(self, limit: int = 50) -> list[dict]:
        return list(reversed(self._treasury_actions[-limit:]))

    # ----- WebSocket fanout ------------------------------------------------

    def subscribe_ws(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._ws_subscribers.append(q)
        return q

    def unsubscribe_ws(self, q: asyncio.Queue) -> None:
        if q in self._ws_subscribers:
            self._ws_subscribers.remove(q)

    async def broadcast(self, event: dict) -> None:
        # Non-blocking fan-out; drop on overflow
        for q in self._ws_subscribers:
            if not q.full():
                await q.put(event)


# Process-wide singleton
state = StateStore()

"""
AKRITA state facade.

Preserves the `state.X(...)` async interface routers + the trace pipeline
use. Under the hood every call opens a short-lived Postgres session (via
the repositories) or talks to Redis (counters + nonces). Multi-tenant:
write methods read `user_id` from the decision/trace/fill dict; read
methods take an optional `user_id` filter (None = cross-user, used by the
public leaderboard). Nonce/counter are scoped per agent_instance. The only
in-process state is the WebSocket fan-out.
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
    SQLAgentInstanceRepo,
    SQLBalanceRepo,
    SQLBuilderProfileRepo,
    SQLConsentRepo,
    SQLDecisionRepo,
    SQLFeedbackRepo,
    SQLFillRepo,
    SQLHedgePositionRepo,
    SQLInventoryRepo,
    SQLKillSwitchRepo,
    SQLOrderRepo,
    SQLTemplateRepo,
    SQLTraceRepo,
    SQLTreasuryActionRepo,
    SQLUserRepo,
)
from shared.models import SYSTEM_USER_ID, InventorySnapshot


class StateStore:
    def __init__(self) -> None:
        self._ws_subscribers: list[asyncio.Queue] = []

    # ----- Decision IDs / nonces (scoped per agent_instance) --------------

    async def next_decision_id(self, scope: str) -> int:
        return await _redis_next_decision_id(scope)

    async def claim_nonce(self, scope: str, nonce: int) -> bool:
        return await _redis_claim_nonce(scope, nonce)

    # ----- Decisions -------------------------------------------------------

    async def store_decision(self, decision_dict: dict) -> None:
        async with async_session_factory()() as session:
            await SQLDecisionRepo(session).store(decision_dict)
            await session.commit()

    async def get_decision(
        self, decision_id: int, agent_role: Optional[str] = None, user_id: Optional[str] = None
    ) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLDecisionRepo(session).get(decision_id, agent_role, user_id)

    async def list_recent_decisions(
        self, limit: int = 20, user_id: Optional[str] = None
    ) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLDecisionRepo(session).list_recent(limit, user_id)

    # ----- Traces ----------------------------------------------------------

    async def store_trace(self, decision_id: int, trace_info: dict) -> None:
        agent_role = trace_info.get("agent_role", "?")
        async with async_session_factory()() as session:
            await SQLTraceRepo(session).store(decision_id, agent_role, trace_info)
            await session.commit()

    async def get_trace(self, decision_id: int, user_id: Optional[str] = None) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLTraceRepo(session).get(decision_id, user_id)

    async def get_trace_by_hash(self, trace_hash: str) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLTraceRepo(session).get_by_hash(trace_hash)

    async def list_recent_traces(
        self, limit: int = 20, user_id: Optional[str] = None
    ) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLTraceRepo(session).list_recent(limit, user_id)

    async def count_traces(self, user_id: Optional[str] = None) -> int:
        async with async_session_factory()() as session:
            return await SQLTraceRepo(session).count(user_id)

    # ----- Inventory -------------------------------------------------------

    async def update_inventory(
        self, snapshot: InventorySnapshot, user_id: str = SYSTEM_USER_ID
    ) -> None:
        async with async_session_factory()() as session:
            await SQLInventoryRepo(session).append(snapshot, user_id)
            await session.commit()

    async def get_inventory(
        self, market_id: str, user_id: str = SYSTEM_USER_ID
    ) -> InventorySnapshot:
        async with async_session_factory()() as session:
            return await SQLInventoryRepo(session).get_latest(market_id, user_id)

    async def all_inventory(self, user_id: Optional[str] = None) -> list[InventorySnapshot]:
        async with async_session_factory()() as session:
            return await SQLInventoryRepo(session).list_latest_all(user_id)

    # ----- Fills -----------------------------------------------------------

    async def record_fill(self, fill_dict: dict) -> None:
        uid = fill_dict.get("user_id") or SYSTEM_USER_ID
        async with async_session_factory()() as session:
            inserted = await SQLFillRepo(session).record(fill_dict)
            if inserted:
                inv_repo = SQLInventoryRepo(session)
                inv = await inv_repo.get_latest(fill_dict["market_id"], uid)
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
                await inv_repo.append(inv, uid)
            await session.commit()

    async def list_fills(self, limit: int = 50, user_id: Optional[str] = None) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLFillRepo(session).list_recent(limit, user_id)

    async def cumulative_builder_fees_usdc(self, user_id: Optional[str] = None) -> float:
        async with async_session_factory()() as session:
            return await SQLFillRepo(session).cumulative_builder_fees_usdc(user_id)

    async def volume_by_user(self) -> dict[str, dict]:
        async with async_session_factory()() as session:
            return await SQLFillRepo(session).volume_by_user()

    # ----- Orders ----------------------------------------------------------

    async def list_open_orders(
        self, market_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLOrderRepo(session).list_open(market_id, user_id)

    # ----- Hedge positions -------------------------------------------------

    async def record_hedge(self, position_dict: dict) -> None:
        async with async_session_factory()() as session:
            await SQLHedgePositionRepo(session).upsert(position_dict)
            await session.commit()

    async def list_open_hedges(self, user_id: Optional[str] = None) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLHedgePositionRepo(session).list_open(user_id)

    # ----- Treasury actions ------------------------------------------------

    async def record_treasury(self, action_dict: dict) -> None:
        async with async_session_factory()() as session:
            await SQLTreasuryActionRepo(session).record(action_dict)
            await session.commit()

    async def list_treasury(self, limit: int = 50, user_id: Optional[str] = None) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLTreasuryActionRepo(session).list_recent(limit, user_id)

    # ----- Balances --------------------------------------------------------

    async def upsert_balance(self, **kwargs) -> None:
        async with async_session_factory()() as session:
            await SQLBalanceRepo(session).upsert(**kwargs)
            await session.commit()

    async def list_user_balances(self, user_id: str) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLBalanceRepo(session).list_for_user(user_id)

    # ----- Users -----------------------------------------------------------

    async def create_user(
        self, handle: str, display_name: Optional[str] = None, msca_address: Optional[str] = None
    ) -> dict:
        async with async_session_factory()() as session:
            row = await SQLUserRepo(session).create(handle, display_name, msca_address)
            await session.commit()
            return row

    async def get_user(self, user_id: str) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLUserRepo(session).get(user_id)

    async def get_user_by_handle(self, handle: str) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLUserRepo(session).get_by_handle(handle)

    async def list_users(self, include_system: bool = False) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLUserRepo(session).list_all(include_system)

    # ----- Builder profiles ------------------------------------------------

    async def upsert_builder_profile(self, **kwargs) -> dict:
        async with async_session_factory()() as session:
            row = await SQLBuilderProfileRepo(session).upsert(**kwargs)
            await session.commit()
            return row

    async def get_builder_profile(self, user_id: str) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLBuilderProfileRepo(session).get_by_user(user_id)

    async def next_agent_id(self) -> int:
        async with async_session_factory()() as session:
            return await SQLBuilderProfileRepo(session).next_agent_id()

    async def set_builder_onchain(
        self, user_id: str, agent_id: int, status: str, tx: Optional[str] = None
    ) -> None:
        async with async_session_factory()() as session:
            await SQLBuilderProfileRepo(session).set_onchain(user_id, agent_id, status, tx)
            await session.commit()

    async def set_builder_status(
        self, user_id: str, status: str, tx: Optional[str] = None
    ) -> None:
        async with async_session_factory()() as session:
            await SQLBuilderProfileRepo(session).set_status(user_id, status, tx)
            await session.commit()

    async def list_builder_profiles(self) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLBuilderProfileRepo(session).list_all()

    # ----- Agent instances -------------------------------------------------

    async def create_agent_instance(self, **kwargs) -> dict:
        async with async_session_factory()() as session:
            row = await SQLAgentInstanceRepo(session).create(**kwargs)
            await session.commit()
            return row

    async def list_enabled_instances(self, archetype: Optional[str] = None) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLAgentInstanceRepo(session).list_enabled(archetype)

    async def list_user_instances(self, user_id: str) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLAgentInstanceRepo(session).list_for_user(user_id)

    async def get_agent_instance(self, instance_id: str) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLAgentInstanceRepo(session).get(instance_id)

    async def set_instance_flags(self, instance_id: str, **kwargs) -> None:
        async with async_session_factory()() as session:
            await SQLAgentInstanceRepo(session).set_flags(instance_id, **kwargs)
            await session.commit()

    # ----- Templates -------------------------------------------------------

    async def list_templates(self) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLTemplateRepo(session).list_all()

    async def get_template(self, key: str) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLTemplateRepo(session).get_by_key(key)

    async def get_default_template(self) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLTemplateRepo(session).get_default()

    # ----- Kill-switch events ----------------------------------------------

    async def create_kill_switch_event(
        self, user_id: str, trigger_source: str, trigger_detail: Optional[dict] = None
    ) -> int:
        async with async_session_factory()() as session:
            event_id = await SQLKillSwitchRepo(session).create(
                user_id, trigger_source, trigger_detail
            )
            await session.commit()
            return event_id

    async def update_kill_switch_event(self, event_id: int, **kwargs) -> None:
        async with async_session_factory()() as session:
            await SQLKillSwitchRepo(session).update_results(event_id, **kwargs)
            await session.commit()

    async def list_kill_switch_events(
        self, limit: int = 20, user_id: Optional[str] = None
    ) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLKillSwitchRepo(session).list_recent(limit, user_id)

    async def get_kill_switch_event(self, event_id: int) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLKillSwitchRepo(session).get(event_id)

    # ----- Feedback events -------------------------------------------------

    async def record_feedback(
        self, user_id: str, event_type: str, delta, **kwargs
    ) -> int:
        async with async_session_factory()() as session:
            event_id = await SQLFeedbackRepo(session).record(
                user_id, event_type, delta, **kwargs
            )
            await session.commit()
            return event_id

    async def list_feedback(self, user_id: str, limit: int = 50) -> list[dict]:
        async with async_session_factory()() as session:
            return await SQLFeedbackRepo(session).list_for_user(user_id, limit)

    async def feedback_by_user(self) -> dict[str, dict]:
        async with async_session_factory()() as session:
            return await SQLFeedbackRepo(session).aggregate_by_user()

    async def mark_feedback_pushed(self, ids: list[int], tx: str) -> None:
        async with async_session_factory()() as session:
            await SQLFeedbackRepo(session).mark_pushed(ids, tx)
            await session.commit()

    # ----- User consents ---------------------------------------------------

    async def record_consent(
        self,
        user_id: str,
        consent_type: str,
        version: str,
        signer_address: str,
        typed_data: dict,
        signature: str,
        onchain_tx: Optional[str] = None,
    ) -> dict:
        async with async_session_factory()() as session:
            row = await SQLConsentRepo(session).record(
                user_id, consent_type, version, signer_address,
                typed_data, signature, onchain_tx,
            )
            await session.commit()
            return row

    async def has_consent(self, user_id: str, consent_type: str, version: str) -> bool:
        async with async_session_factory()() as session:
            return await SQLConsentRepo(session).has_consent(user_id, consent_type, version)

    async def get_consent(self, user_id: str, consent_type: str) -> Optional[dict]:
        async with async_session_factory()() as session:
            return await SQLConsentRepo(session).get(user_id, consent_type)

    async def set_consent_onchain_tx(self, id: int, tx: str) -> None:
        async with async_session_factory()() as session:
            await SQLConsentRepo(session).set_onchain_tx(id, tx)
            await session.commit()

    # ----- Leaderboard aggregation (cross-user) ---------------------------

    async def decision_stats_by_user(self) -> dict[str, dict]:
        async with async_session_factory()() as session:
            return await SQLDecisionRepo(session).stats_by_user()

    async def trace_count_by_user(self) -> dict[str, int]:
        async with async_session_factory()() as session:
            return await SQLTraceRepo(session).count_by_user()

    async def latest_trace_by_user(self) -> dict[str, dict]:
        async with async_session_factory()() as session:
            return await SQLTraceRepo(session).latest_by_user()

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

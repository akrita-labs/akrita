"""Repository Protocol surface.

Every persistent collection exposes its read/write methods through a
Protocol here. Routers and state.py depend on these Protocols, not on
the concrete SQLAlchemy implementation, so we can swap or fake easily.
"""
from __future__ import annotations

from typing import Optional, Protocol

from shared.models import InventorySnapshot


class DecisionRepo(Protocol):
    async def store(self, decision: dict) -> None: ...
    async def get(self, decision_id: int, agent_role: Optional[str] = None) -> Optional[dict]: ...
    async def list_recent(self, limit: int = 20) -> list[dict]: ...


class TraceRepo(Protocol):
    async def store(self, decision_id: int, agent_role: str, trace_info: dict) -> None: ...
    async def get(self, decision_id: int) -> Optional[dict]: ...
    async def get_by_hash(self, trace_hash: str) -> Optional[dict]: ...


class OrderRepo(Protocol):
    async def store(self, order: dict) -> None: ...
    async def update_status(self, order_id: str, status: str) -> None: ...
    async def get(self, order_id: str) -> Optional[dict]: ...
    async def list_open(self, market_id: Optional[str] = None) -> list[dict]: ...


class FillRepo(Protocol):
    async def record(self, fill: dict) -> bool:
        """Idempotent insert by (tx_hash, log_index). Returns True if newly inserted."""
        ...
    async def list_recent(self, limit: int = 50) -> list[dict]: ...
    async def cumulative_builder_fees_usdc(self) -> float: ...


class HedgePositionRepo(Protocol):
    async def upsert(self, position: dict) -> None: ...
    async def list_open(self) -> list[dict]: ...
    async def get(self, venue: str, venue_position_id: str) -> Optional[dict]: ...


class TreasuryActionRepo(Protocol):
    async def record(self, action: dict) -> None: ...
    async def list_recent(self, limit: int = 50) -> list[dict]: ...
    async def mark_settled(self, action_id: int, tx_hash: str) -> None: ...


class BalanceRepo(Protocol):
    async def upsert(
        self,
        wallet_role: str,
        wallet_addr: str,
        chain: str,
        token: str,
        amount: float,
        source: str = "chain",
    ) -> None: ...
    async def get(
        self, wallet_addr: str, chain: str, token: str, source: str = "chain"
    ) -> Optional[float]: ...
    async def list_for_wallet(self, wallet_addr: str) -> list[dict]: ...


class InventoryRepo(Protocol):
    async def append(self, snapshot: InventorySnapshot) -> None: ...
    async def get_latest(self, market_id: str) -> InventorySnapshot: ...
    async def list_latest_all(self) -> list[InventorySnapshot]: ...


class AdapterEventRepo(Protocol):
    async def record(
        self,
        adapter: str,
        event_type: str,
        payload: dict,
        external_id: Optional[str] = None,
    ) -> bool:
        """Idempotent on (adapter, external_id) when external_id given.
        Returns True if newly inserted, False if duplicate.
        """
        ...
    async def list_recent(self, adapter: str, limit: int = 50) -> list[dict]: ...


class TemplateRepo(Protocol):
    async def list_all(self) -> list[dict]: ...
    async def get_by_key(self, key: str) -> Optional[dict]: ...
    async def get_default(self) -> Optional[dict]: ...


class KillSwitchRepo(Protocol):
    async def create(
        self, user_id: str, trigger_source: str, trigger_detail: Optional[dict] = None
    ) -> int: ...
    async def update_results(
        self,
        event_id: int,
        *,
        nomos_result: Optional[dict] = None,
        spatha_result: Optional[dict] = None,
        agros_result: Optional[dict] = None,
        trace_decision_id: Optional[int] = None,
        trace_hash: Optional[str] = None,
        arc_tx: Optional[str] = None,
        status: Optional[str] = None,
        completed: bool = False,
    ) -> None: ...
    async def list_recent(self, limit: int = 20, user_id: Optional[str] = None) -> list[dict]: ...
    async def get(self, event_id: int) -> Optional[dict]: ...


class FeedbackRepo(Protocol):
    async def record(
        self,
        user_id: str,
        event_type: str,
        delta,
        *,
        erc8004_id: Optional[int] = None,
        ref: Optional[dict] = None,
    ) -> int: ...
    async def list_for_user(self, user_id: str, limit: int = 50) -> list[dict]: ...
    async def aggregate_by_user(self) -> dict[str, dict]: ...
    async def mark_pushed(self, event_ids: list[int], onchain_tx: str) -> None: ...


class ConsentRepo(Protocol):
    async def record(
        self,
        user_id: str,
        consent_type: str,
        version: str,
        signer_address: str,
        typed_data: dict,
        signature: str,
        onchain_tx: Optional[str] = None,
    ) -> dict: ...
    async def has_consent(self, user_id: str, consent_type: str, version: str) -> bool: ...
    async def get(self, user_id: str, consent_type: str) -> Optional[dict]: ...
    async def set_onchain_tx(self, consent_id: int, tx: str) -> None: ...

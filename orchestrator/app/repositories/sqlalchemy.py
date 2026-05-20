"""SQLAlchemy-backed repository implementations.

Each repo takes an `AsyncSession` in its constructor. Caller owns the
transaction (commit / rollback). Reads use `session.execute` /
`session.scalars`; writes use `session.add` or upsert constructs.
"""
from __future__ import annotations

import time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.app.db.models import (
    AdapterEvent,
    Balance,
    Decision,
    Fill,
    HedgePosition,
    InventorySnapshot as InventorySnapshotRow,
    Order,
    Trace,
    TreasuryAction,
)
from shared.models import InventorySnapshot


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

_DECISION_TYPE_BY_ROLE = {
    "nomos": "pricing",
    "spatha": "hedge",
    "agros": "treasury",
}


def _to_dict(row) -> dict:
    """Convert a SQLAlchemy row into a plain dict for the legacy state.py
    interface. We dump explicit columns + merge in payload JSONB for
    Decision rows."""
    out: dict = {}
    for col in row.__table__.columns:
        v = getattr(row, col.name)
        out[col.name] = v
    payload = out.pop("payload", None)
    if isinstance(payload, dict):
        # Payload fields shadow the envelope columns when present.
        out = {**out, **payload}
    return out


class SQLDecisionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(self, decision: dict) -> None:
        agent_role = decision.get("agent_role", "?")
        row = Decision(
            decision_id=int(decision["decision_id"]),
            agent_role=agent_role,
            decision_type=_DECISION_TYPE_BY_ROLE.get(agent_role, agent_role),
            nonce=int(decision.get("nonce", 0)),
            ts_ms=int(decision.get("ts_ms", time.time() * 1000)),
            rationale_hash=decision.get("rationale_hash", ""),
            payload=decision,
            approved=bool(decision.get("risk_passed", True)),
            rejection_reason=decision.get("risk_reason"),
        )
        self.session.add(row)
        await self.session.flush()

    async def get(self, decision_id: int, agent_role: Optional[str] = None) -> Optional[dict]:
        stmt = select(Decision).where(Decision.decision_id == decision_id)
        if agent_role:
            stmt = stmt.where(Decision.agent_role == agent_role)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def list_recent(self, limit: int = 20) -> list[dict]:
        stmt = select(Decision).order_by(Decision.ts_ms.desc()).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------

class SQLTraceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(self, decision_id: int, agent_role: str, trace_info: dict) -> None:
        body = trace_info.get("body") or {}
        row = Trace(
            decision_id=decision_id,
            agent_role=agent_role,
            trace_hash=trace_info["trace_hash"],
            cid=trace_info.get("ipfs_cid") or trace_info.get("cid"),
            arc_tx=trace_info.get("arc_tx_hash") or trace_info.get("arc_tx"),
            arc_block=trace_info.get("arc_block"),
            body=body if isinstance(body, dict) else dict(body),
        )
        # Upsert so retries don't violate the unique constraint.
        stmt = (
            pg_insert(Trace)
            .values(
                decision_id=row.decision_id,
                agent_role=row.agent_role,
                trace_hash=row.trace_hash,
                cid=row.cid,
                arc_tx=row.arc_tx,
                arc_block=row.arc_block,
                body=row.body,
            )
            .on_conflict_do_update(
                constraint="uq_traces_decision",
                set_={
                    "trace_hash": row.trace_hash,
                    "cid": row.cid,
                    "arc_tx": row.arc_tx,
                    "arc_block": row.arc_block,
                    "body": row.body,
                },
            )
        )
        await self.session.execute(stmt)

    async def get(self, decision_id: int) -> Optional[dict]:
        stmt = select(Trace).where(Trace.decision_id == decision_id)
        row = (await self.session.execute(stmt)).scalars().first()
        return _to_dict(row) if row else None

    async def get_by_hash(self, trace_hash: str) -> Optional[dict]:
        stmt = select(Trace).where(Trace.trace_hash == trace_hash)
        row = (await self.session.execute(stmt)).scalars().first()
        return _to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

class SQLOrderRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(self, order: dict) -> None:
        row = Order(
            order_id=order["order_id"],
            decision_pk=order.get("decision_pk"),
            market_id=order["market_id"],
            side=order["side"],
            price=float(order["price"]),
            size=float(order["size"]),
            status=order.get("status", "open"),
            builder_code=order.get("builder_code"),
        )
        self.session.add(row)
        await self.session.flush()

    async def update_status(self, order_id: str, status: str) -> None:
        stmt = select(Order).where(Order.order_id == order_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row:
            row.status = status

    async def get(self, order_id: str) -> Optional[dict]:
        stmt = select(Order).where(Order.order_id == order_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def list_open(self, market_id: Optional[str] = None) -> list[dict]:
        stmt = select(Order).where(Order.status == "open")
        if market_id:
            stmt = stmt.where(Order.market_id == market_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Fills
# ---------------------------------------------------------------------------

class SQLFillRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, fill: dict) -> bool:
        """Insert with dedup on (tx_hash, log_index). Returns False on duplicate."""
        tx_hash = fill.get("tx_hash", "")
        log_index = int(fill.get("log_index", 0))
        stmt = (
            pg_insert(Fill)
            .values(
                tx_hash=tx_hash,
                log_index=log_index,
                order_id=fill.get("order_id"),
                market_id=fill["market_id"],
                side=fill["side"],
                price=float(fill["price"]),
                size=float(fill["size"]),
                builder_fee_usdc=float(fill.get("builder_fee_usdc", 0.0)),
                ts_ms=int(fill.get("ts_ms", time.time() * 1000)),
            )
            .on_conflict_do_nothing(constraint="uq_fills_tx_log")
            .returning(Fill.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_recent(self, limit: int = 50) -> list[dict]:
        stmt = select(Fill).order_by(Fill.ts_ms.desc()).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def cumulative_builder_fees_usdc(self) -> float:
        from sqlalchemy import func
        stmt = select(func.coalesce(func.sum(Fill.builder_fee_usdc), 0.0))
        return float((await self.session.execute(stmt)).scalar_one())


# ---------------------------------------------------------------------------
# Hedge positions
# ---------------------------------------------------------------------------

class SQLHedgePositionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, position: dict) -> None:
        venue = position.get("venue", "")
        venue_position_id = str(position.get("position_id") or position.get("venue_position_id"))
        stmt = (
            pg_insert(HedgePosition)
            .values(
                venue=venue,
                venue_position_id=venue_position_id,
                decision_pk=position.get("decision_pk"),
                instrument=position.get("instrument", ""),
                side=position.get("side", ""),
                size=float(position.get("size", 0.0)),
                entry_price=float(position.get("entry_price", 0.0)),
                margin_asset=position.get("margin_asset", "USDC"),
                margin_amount=float(position.get("margin_amount", 0.0)),
                status=position.get("status", "open"),
                pnl_usdc=float(position.get("pnl_usdc", 0.0)),
            )
            .on_conflict_do_update(
                constraint="uq_hedge_venue_id",
                set_={
                    "status": position.get("status", "open"),
                    "pnl_usdc": float(position.get("pnl_usdc", 0.0)),
                    "size": float(position.get("size", 0.0)),
                },
            )
        )
        await self.session.execute(stmt)

    async def list_open(self) -> list[dict]:
        stmt = select(HedgePosition).where(HedgePosition.status == "open")
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def get(self, venue: str, venue_position_id: str) -> Optional[dict]:
        stmt = select(HedgePosition).where(
            HedgePosition.venue == venue,
            HedgePosition.venue_position_id == venue_position_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Treasury actions
# ---------------------------------------------------------------------------

class SQLTreasuryActionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, action: dict) -> None:
        row = TreasuryAction(
            decision_pk=action.get("decision_pk"),
            action=action["action"],
            amount=float(action.get("amount") or action.get("usdc_amount") or 0.0),
            src_chain=action.get("src_chain"),
            dst_chain=action.get("dst_chain"),
            status=action.get("status", "pending"),
            tx_hash=action.get("tx_hash"),
            external_ref=action.get("external_ref") or action.get("src_tx"),
        )
        self.session.add(row)
        await self.session.flush()

    async def list_recent(self, limit: int = 50) -> list[dict]:
        stmt = select(TreasuryAction).order_by(TreasuryAction.created_at.desc()).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def mark_settled(self, action_id: int, tx_hash: str) -> None:
        from sqlalchemy import update
        from datetime import datetime, timezone
        stmt = (
            update(TreasuryAction)
            .where(TreasuryAction.id == action_id)
            .values(status="settled", tx_hash=tx_hash, settled_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------

class SQLBalanceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        wallet_role: str,
        wallet_addr: str,
        chain: str,
        token: str,
        amount: float,
        source: str = "chain",
    ) -> None:
        stmt = (
            pg_insert(Balance)
            .values(
                wallet_role=wallet_role,
                wallet_addr=wallet_addr,
                chain=chain,
                token=token,
                amount=amount,
                source=source,
            )
            .on_conflict_do_update(
                constraint="uq_balance_key",
                set_={"amount": amount, "wallet_role": wallet_role},
            )
        )
        await self.session.execute(stmt)

    async def get(
        self, wallet_addr: str, chain: str, token: str, source: str = "chain"
    ) -> Optional[float]:
        stmt = select(Balance.amount).where(
            Balance.wallet_addr == wallet_addr,
            Balance.chain == chain,
            Balance.token == token,
            Balance.source == source,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return float(row) if row is not None else None

    async def list_for_wallet(self, wallet_addr: str) -> list[dict]:
        stmt = select(Balance).where(Balance.wallet_addr == wallet_addr)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

class SQLInventoryRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, snapshot: InventorySnapshot) -> None:
        row = InventorySnapshotRow(
            market_id=snapshot.market_id,
            net_exposure=snapshot.net_exposure,
            long_size=snapshot.long_size,
            short_size=snapshot.short_size,
            snapshot_ts_ms=snapshot.snapshot_ts_ms,
        )
        self.session.add(row)
        await self.session.flush()

    async def get_latest(self, market_id: str) -> InventorySnapshot:
        stmt = (
            select(InventorySnapshotRow)
            .where(InventorySnapshotRow.market_id == market_id)
            .order_by(InventorySnapshotRow.snapshot_ts_ms.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return InventorySnapshot(
                market_id=market_id,
                net_exposure=0.0,
                long_size=0.0,
                short_size=0.0,
                snapshot_ts_ms=int(time.time() * 1000),
            )
        return InventorySnapshot(
            market_id=row.market_id,
            net_exposure=row.net_exposure,
            long_size=row.long_size,
            short_size=row.short_size,
            snapshot_ts_ms=row.snapshot_ts_ms,
        )

    async def list_latest_all(self) -> list[InventorySnapshot]:
        # Postgres-specific DISTINCT ON for latest-per-market.
        from sqlalchemy import text
        stmt = text(
            "SELECT DISTINCT ON (market_id) "
            "market_id, net_exposure, long_size, short_size, snapshot_ts_ms "
            "FROM inventory_snapshots ORDER BY market_id, snapshot_ts_ms DESC"
        )
        result = await self.session.execute(stmt)
        return [
            InventorySnapshot(
                market_id=r.market_id,
                net_exposure=r.net_exposure,
                long_size=r.long_size,
                short_size=r.short_size,
                snapshot_ts_ms=r.snapshot_ts_ms,
            )
            for r in result.mappings()
        ]


# ---------------------------------------------------------------------------
# Adapter events
# ---------------------------------------------------------------------------

class SQLAdapterEventRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        adapter: str,
        event_type: str,
        payload: dict,
        external_id: Optional[str] = None,
    ) -> bool:
        stmt = pg_insert(AdapterEvent).values(
            adapter=adapter,
            event_type=event_type,
            external_id=external_id,
            payload=payload,
        )
        if external_id is not None:
            stmt = stmt.on_conflict_do_nothing(index_elements=["adapter", "external_id"])
        stmt = stmt.returning(AdapterEvent.id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_recent(self, adapter: str, limit: int = 50) -> list[dict]:
        stmt = (
            select(AdapterEvent)
            .where(AdapterEvent.adapter == adapter)
            .order_by(AdapterEvent.received_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

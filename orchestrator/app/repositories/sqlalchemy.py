"""SQLAlchemy-backed repository implementations.

Each repo takes an `AsyncSession` in its constructor. Caller owns the
transaction (commit / rollback). Reads use `session.execute` /
`session.scalars`; writes use `session.add` or upsert constructs.

Multi-tenant: writes set `user_id` (from the decision/trace dict, default
SYSTEM_USER_ID for back-compat) and `agent_instance_id` where applicable;
reads accept an optional `user_id` filter for row-level isolation (None =
cross-user, used by the public leaderboard + internal aggregation).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.app.db.models import (
    AdapterEvent,
    AgentInstance,
    Balance,
    BuilderProfile,
    Decision,
    FeedbackEvent,
    Fill,
    HedgePosition,
    InventorySnapshot as InventorySnapshotRow,
    KillSwitchEvent,
    Order,
    Template,
    Trace,
    TreasuryAction,
    User,
    UserConsent,
)
from shared.models import SYSTEM_USER_ID, InventorySnapshot


_DECISION_TYPE_BY_ROLE = {"nomos": "pricing", "spatha": "hedge", "agros": "treasury"}


def _to_dict(row) -> dict:
    """SQLAlchemy row -> plain dict; merge Decision.payload over the columns."""
    out: dict = {}
    for col in row.__table__.columns:
        out[col.name] = getattr(row, col.name)
    payload = out.pop("payload", None)
    if isinstance(payload, dict):
        out = {**out, **payload}
    return out


def _uid(d: dict) -> str:
    return d.get("user_id") or SYSTEM_USER_ID


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

class SQLDecisionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(self, decision: dict) -> None:
        agent_role = decision.get("agent_role", "?")
        row = Decision(
            user_id=_uid(decision),
            agent_instance_id=decision.get("agent_instance_id"),
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

    async def get(
        self, decision_id: int, agent_role: Optional[str] = None, user_id: Optional[str] = None
    ) -> Optional[dict]:
        stmt = select(Decision).where(Decision.decision_id == decision_id)
        if agent_role:
            stmt = stmt.where(Decision.agent_role == agent_role)
        if user_id:
            stmt = stmt.where(Decision.user_id == user_id)
        row = (await self.session.execute(stmt)).scalars().first()
        return _to_dict(row) if row else None

    async def list_recent(self, limit: int = 20, user_id: Optional[str] = None) -> list[dict]:
        stmt = select(Decision).order_by(Decision.ts_ms.desc()).limit(limit)
        if user_id:
            stmt = stmt.where(Decision.user_id == user_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def stats_by_user(self) -> dict[str, dict]:
        """Per-user decision count + last-activity ts, split by archetype role
        (for the leaderboard's agent-uptime column)."""
        stmt = select(
            Decision.user_id,
            Decision.agent_role,
            func.count(Decision.id).label("n"),
            func.max(Decision.ts_ms).label("last_ts"),
        ).group_by(Decision.user_id, Decision.agent_role)
        out: dict[str, dict] = {}
        for r in (await self.session.execute(stmt)).all():
            u = out.setdefault(r.user_id, {"decisions": 0, "last_ts_ms": 0, "by_role": {}})
            u["decisions"] += int(r.n)
            u["last_ts_ms"] = max(u["last_ts_ms"], int(r.last_ts or 0))
            u["by_role"][r.agent_role] = {"decisions": int(r.n), "last_ts_ms": int(r.last_ts or 0)}
        return out


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------

class SQLTraceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(self, decision_id: int, agent_role: str, trace_info: dict) -> None:
        body = trace_info.get("body") or {}
        values = dict(
            user_id=trace_info.get("user_id") or SYSTEM_USER_ID,
            agent_instance_id=trace_info.get("agent_instance_id"),
            decision_id=decision_id,
            agent_role=agent_role,
            trace_hash=trace_info["trace_hash"],
            cid=trace_info.get("ipfs_cid") or trace_info.get("cid"),
            arc_tx=trace_info.get("arc_tx_hash") or trace_info.get("arc_tx"),
            arc_block=trace_info.get("arc_block"),
            body=body if isinstance(body, dict) else dict(body),
        )
        stmt = (
            pg_insert(Trace)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_traces_instance_decision",
                set_={
                    "trace_hash": values["trace_hash"],
                    "cid": values["cid"],
                    "arc_tx": values["arc_tx"],
                    "arc_block": values["arc_block"],
                    "body": values["body"],
                },
            )
        )
        await self.session.execute(stmt)

    async def get(self, decision_id: int, user_id: Optional[str] = None) -> Optional[dict]:
        stmt = select(Trace).where(Trace.decision_id == decision_id)
        if user_id:
            stmt = stmt.where(Trace.user_id == user_id)
        row = (await self.session.execute(stmt)).scalars().first()
        return _to_dict(row) if row else None

    async def get_by_hash(self, trace_hash: str) -> Optional[dict]:
        stmt = select(Trace).where(Trace.trace_hash == trace_hash)
        row = (await self.session.execute(stmt)).scalars().first()
        return _to_dict(row) if row else None

    async def list_recent(self, limit: int = 20, user_id: Optional[str] = None) -> list[dict]:
        stmt = select(Trace).order_by(Trace.id.desc()).limit(limit)
        if user_id:
            stmt = stmt.where(Trace.user_id == user_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def count(self, user_id: Optional[str] = None) -> int:
        stmt = select(func.count(Trace.id))
        if user_id:
            stmt = stmt.where(Trace.user_id == user_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_by_user(self) -> dict[str, int]:
        stmt = select(Trace.user_id, func.count(Trace.id)).group_by(Trace.user_id)
        return {r[0]: int(r[1]) for r in (await self.session.execute(stmt)).all()}

    async def latest_by_user(self) -> dict[str, dict]:
        """Most recent committed trace per user (hash/cid/arc_tx) for the
        leaderboard's verifiable-anchor column. DISTINCT ON (user_id)."""
        stmt = text(
            "SELECT DISTINCT ON (user_id) user_id, trace_hash, cid, arc_tx, arc_block, "
            "decision_id, agent_role, committed_at "
            "FROM traces ORDER BY user_id, id DESC"
        )
        rows = (await self.session.execute(stmt)).mappings().all()
        return {
            r["user_id"]: {
                "trace_hash": r["trace_hash"],
                "cid": r["cid"],
                "arc_tx": r["arc_tx"],
                "arc_block": r["arc_block"],
                "decision_id": r["decision_id"],
                "agent_role": r["agent_role"],
                "committed_at": r["committed_at"].isoformat() if r["committed_at"] else None,
            }
            for r in rows
        }


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

class SQLOrderRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(self, order: dict) -> None:
        row = Order(
            user_id=_uid(order),
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
        row = (await self.session.execute(
            select(Order).where(Order.order_id == order_id)
        )).scalar_one_or_none()
        if row:
            row.status = status

    async def get(self, order_id: str) -> Optional[dict]:
        row = (await self.session.execute(
            select(Order).where(Order.order_id == order_id)
        )).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def list_open(
        self, market_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> list[dict]:
        stmt = select(Order).where(Order.status == "open")
        if market_id:
            stmt = stmt.where(Order.market_id == market_id)
        if user_id:
            stmt = stmt.where(Order.user_id == user_id)
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
        stmt = (
            pg_insert(Fill)
            .values(
                user_id=_uid(fill),
                tx_hash=fill.get("tx_hash", ""),
                log_index=int(fill.get("log_index", 0)),
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
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def list_recent(self, limit: int = 50, user_id: Optional[str] = None) -> list[dict]:
        stmt = select(Fill).order_by(Fill.ts_ms.desc()).limit(limit)
        if user_id:
            stmt = stmt.where(Fill.user_id == user_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def cumulative_builder_fees_usdc(self, user_id: Optional[str] = None) -> float:
        stmt = select(func.coalesce(func.sum(Fill.builder_fee_usdc), 0.0))
        if user_id:
            stmt = stmt.where(Fill.user_id == user_id)
        return float((await self.session.execute(stmt)).scalar_one())

    async def volume_by_user(self) -> dict[str, dict]:
        """Per-user aggregate for the leaderboard: notional volume, fees, fill count."""
        stmt = select(
            Fill.user_id,
            func.coalesce(func.sum(Fill.price * Fill.size), 0.0).label("volume"),
            func.coalesce(func.sum(Fill.builder_fee_usdc), 0.0).label("fees"),
            func.count(Fill.id).label("fills"),
        ).group_by(Fill.user_id)
        rows = (await self.session.execute(stmt)).all()
        return {
            r.user_id: {"volume": float(r.volume), "fees": float(r.fees), "fills": int(r.fills)}
            for r in rows
        }


# ---------------------------------------------------------------------------
# Hedge positions
# ---------------------------------------------------------------------------

class SQLHedgePositionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, position: dict) -> None:
        venue_position_id = str(position.get("position_id") or position.get("venue_position_id"))
        stmt = (
            pg_insert(HedgePosition)
            .values(
                user_id=_uid(position),
                venue=position.get("venue", ""),
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

    async def list_open(self, user_id: Optional[str] = None) -> list[dict]:
        stmt = select(HedgePosition).where(HedgePosition.status == "open")
        if user_id:
            stmt = stmt.where(HedgePosition.user_id == user_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def get(self, venue: str, venue_position_id: str) -> Optional[dict]:
        row = (await self.session.execute(
            select(HedgePosition).where(
                HedgePosition.venue == venue,
                HedgePosition.venue_position_id == venue_position_id,
            )
        )).scalar_one_or_none()
        return _to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Treasury actions
# ---------------------------------------------------------------------------

class SQLTreasuryActionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, action: dict) -> None:
        row = TreasuryAction(
            user_id=_uid(action),
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

    async def list_recent(self, limit: int = 50, user_id: Optional[str] = None) -> list[dict]:
        stmt = select(TreasuryAction).order_by(TreasuryAction.created_at.desc()).limit(limit)
        if user_id:
            stmt = stmt.where(TreasuryAction.user_id == user_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def mark_settled(self, action_id: int, tx_hash: str) -> None:
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
        user_id: str = SYSTEM_USER_ID,
    ) -> None:
        stmt = (
            pg_insert(Balance)
            .values(
                user_id=user_id,
                wallet_role=wallet_role,
                wallet_addr=wallet_addr,
                chain=chain,
                token=token,
                amount=amount,
                source=source,
            )
            .on_conflict_do_update(
                constraint="uq_balance_key",
                set_={"amount": amount, "wallet_role": wallet_role, "user_id": user_id},
            )
        )
        await self.session.execute(stmt)

    async def get(
        self, wallet_addr: str, chain: str, token: str, source: str = "chain"
    ) -> Optional[float]:
        row = (await self.session.execute(
            select(Balance.amount).where(
                Balance.wallet_addr == wallet_addr,
                Balance.chain == chain,
                Balance.token == token,
                Balance.source == source,
            )
        )).scalar_one_or_none()
        return float(row) if row is not None else None

    async def list_for_user(self, user_id: str) -> list[dict]:
        rows = (await self.session.execute(
            select(Balance).where(Balance.user_id == user_id)
        )).scalars().all()
        return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

class SQLInventoryRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, snapshot: InventorySnapshot, user_id: str = SYSTEM_USER_ID) -> None:
        row = InventorySnapshotRow(
            user_id=user_id,
            market_id=snapshot.market_id,
            net_exposure=snapshot.net_exposure,
            long_size=snapshot.long_size,
            short_size=snapshot.short_size,
            snapshot_ts_ms=snapshot.snapshot_ts_ms,
        )
        self.session.add(row)
        await self.session.flush()

    async def get_latest(self, market_id: str, user_id: str = SYSTEM_USER_ID) -> InventorySnapshot:
        stmt = (
            select(InventorySnapshotRow)
            .where(
                InventorySnapshotRow.market_id == market_id,
                InventorySnapshotRow.user_id == user_id,
            )
            .order_by(InventorySnapshotRow.snapshot_ts_ms.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return InventorySnapshot(
                market_id=market_id, net_exposure=0.0, long_size=0.0,
                short_size=0.0, snapshot_ts_ms=int(time.time() * 1000),
            )
        return InventorySnapshot(
            market_id=row.market_id, net_exposure=row.net_exposure,
            long_size=row.long_size, short_size=row.short_size,
            snapshot_ts_ms=row.snapshot_ts_ms,
        )

    async def list_latest_all(self, user_id: Optional[str] = None) -> list[InventorySnapshot]:
        # DISTINCT ON (market_id) latest per market, optionally scoped to a user.
        where = "WHERE user_id = :uid " if user_id else ""
        stmt = text(
            "SELECT DISTINCT ON (market_id) "
            "market_id, net_exposure, long_size, short_size, snapshot_ts_ms "
            f"FROM inventory_snapshots {where}"
            "ORDER BY market_id, snapshot_ts_ms DESC"
        )
        params = {"uid": user_id} if user_id else {}
        result = await self.session.execute(stmt, params)
        return [
            InventorySnapshot(
                market_id=r.market_id, net_exposure=r.net_exposure,
                long_size=r.long_size, short_size=r.short_size,
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
        user_id: Optional[str] = None,
    ) -> bool:
        stmt = pg_insert(AdapterEvent).values(
            adapter=adapter,
            event_type=event_type,
            external_id=external_id,
            payload=payload,
            user_id=user_id,
        )
        if external_id is not None:
            stmt = stmt.on_conflict_do_nothing(index_elements=["adapter", "external_id"])
        stmt = stmt.returning(AdapterEvent.id)
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def list_recent(self, adapter: str, limit: int = 50) -> list[dict]:
        rows = (await self.session.execute(
            select(AdapterEvent)
            .where(AdapterEvent.adapter == adapter)
            .order_by(AdapterEvent.received_at.desc())
            .limit(limit)
        )).scalars().all()
        return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class SQLUserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        handle: str,
        display_name: Optional[str] = None,
        msca_address: Optional[str] = None,
        is_system: bool = False,
    ) -> dict:
        row = User(
            handle=handle,
            display_name=display_name,
            msca_address=msca_address,
            is_system=is_system,
        )
        self.session.add(row)
        await self.session.flush()
        return _to_dict(row)

    async def get(self, user_id: str) -> Optional[dict]:
        row = (await self.session.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def get_by_handle(self, handle: str) -> Optional[dict]:
        row = (await self.session.execute(
            select(User).where(User.handle == handle)
        )).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def list_all(self, include_system: bool = False) -> list[dict]:
        stmt = select(User).order_by(User.created_at.asc())
        if not include_system:
            stmt = stmt.where(User.is_system.is_(False))
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Builder profiles
# ---------------------------------------------------------------------------

class SQLBuilderProfileRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        user_id: str,
        builder_code: str,
        poly_api_key_enc: Optional[bytes] = None,
        poly_api_secret_enc: Optional[bytes] = None,
        poly_api_passphrase_enc: Optional[bytes] = None,
        poly_signer_enc: Optional[bytes] = None,
        poly_collateral_ready: bool = False,
    ) -> dict:
        set_: dict = {"builder_code": builder_code, "poly_collateral_ready": poly_collateral_ready}
        for col, val in (
            ("poly_api_key_enc", poly_api_key_enc),
            ("poly_api_secret_enc", poly_api_secret_enc),
            ("poly_api_passphrase_enc", poly_api_passphrase_enc),
            ("poly_signer_enc", poly_signer_enc),
        ):
            if val is not None:
                set_[col] = val
        stmt = (
            pg_insert(BuilderProfile)
            .values(
                user_id=user_id,
                builder_code=builder_code,
                poly_api_key_enc=poly_api_key_enc,
                poly_api_secret_enc=poly_api_secret_enc,
                poly_api_passphrase_enc=poly_api_passphrase_enc,
                poly_signer_enc=poly_signer_enc,
                poly_collateral_ready=poly_collateral_ready,
            )
            .on_conflict_do_update(constraint="uq_builder_profiles_user", set_=set_)
            .returning(BuilderProfile.id)
        )
        await self.session.execute(stmt)
        return await self.get_by_user(user_id)  # type: ignore[return-value]

    async def get_by_user(self, user_id: str) -> Optional[dict]:
        row = (await self.session.execute(
            select(BuilderProfile).where(BuilderProfile.user_id == user_id)
        )).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def get_by_agent_id(self, agent_id: int) -> Optional[dict]:
        row = (await self.session.execute(
            select(BuilderProfile).where(BuilderProfile.onchain_agent_id == agent_id)
        )).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def next_agent_id(self) -> int:
        """Allocate the next on-chain agentId. User agents start at 100 to leave
        the three system agents (1/2/3) untouched."""
        cur = (await self.session.execute(
            select(func.max(BuilderProfile.onchain_agent_id))
        )).scalar_one()
        return max(int(cur or 0), 99) + 1

    async def set_onchain(
        self, user_id: str, agent_id: int, status: str, tx: Optional[str] = None
    ) -> None:
        await self.session.execute(
            update(BuilderProfile)
            .where(BuilderProfile.user_id == user_id)
            .values(onchain_agent_id=agent_id, registration_status=status, registration_tx=tx)
        )

    async def set_status(self, user_id: str, status: str, tx: Optional[str] = None) -> None:
        vals: dict = {"registration_status": status}
        if tx is not None:
            vals["registration_tx"] = tx
        await self.session.execute(
            update(BuilderProfile).where(BuilderProfile.user_id == user_id).values(**vals)
        )

    async def list_all(self) -> list[dict]:
        rows = (await self.session.execute(select(BuilderProfile))).scalars().all()
        return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Agent instances
# ---------------------------------------------------------------------------

class SQLAgentInstanceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        user_id: str,
        archetype: str,
        name: str = "default",
        enabled: bool = False,
        params: Optional[dict] = None,
    ) -> dict:
        row = AgentInstance(
            user_id=user_id,
            archetype=archetype,
            name=name,
            enabled=enabled,
            params=params or {},
        )
        self.session.add(row)
        await self.session.flush()
        return _to_dict(row)

    async def get(self, instance_id: str) -> Optional[dict]:
        row = (await self.session.execute(
            select(AgentInstance).where(AgentInstance.id == instance_id)
        )).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def list_enabled(self, archetype: Optional[str] = None) -> list[dict]:
        stmt = select(AgentInstance).where(
            AgentInstance.enabled.is_(True), AgentInstance.kill_switch.is_(False)
        )
        if archetype:
            stmt = stmt.where(AgentInstance.archetype == archetype)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def list_for_user(self, user_id: str) -> list[dict]:
        rows = (await self.session.execute(
            select(AgentInstance).where(AgentInstance.user_id == user_id)
        )).scalars().all()
        return [_to_dict(r) for r in rows]

    async def set_flags(
        self,
        instance_id: str,
        enabled: Optional[bool] = None,
        kill_switch: Optional[bool] = None,
        params: Optional[dict] = None,
    ) -> None:
        vals: dict = {}
        if enabled is not None:
            vals["enabled"] = enabled
        if kill_switch is not None:
            vals["kill_switch"] = kill_switch
        if params is not None:
            vals["params"] = params
        if vals:
            await self.session.execute(
                update(AgentInstance).where(AgentInstance.id == instance_id).values(**vals)
            )


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class SQLTemplateRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[dict]:
        rows = (await self.session.execute(
            select(Template).order_by(Template.key.asc())
        )).scalars().all()
        return [_to_dict(r) for r in rows]

    async def get_by_key(self, key: str) -> Optional[dict]:
        row = (await self.session.execute(
            select(Template).where(Template.key == key)
        )).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def get_default(self) -> Optional[dict]:
        row = (await self.session.execute(
            select(Template).where(Template.is_default.is_(True)).limit(1)
        )).scalar_one_or_none()
        return _to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Kill-switch events
# ---------------------------------------------------------------------------

class SQLKillSwitchRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, user_id: str, trigger_source: str, trigger_detail: Optional[dict] = None
    ) -> int:
        row = KillSwitchEvent(
            user_id=user_id,
            trigger_source=trigger_source,
            trigger_detail=trigger_detail or {},
        )
        self.session.add(row)
        await self.session.flush()
        return int(row.id)

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
    ) -> None:
        vals: dict = {}
        if nomos_result is not None:
            vals["nomos_result"] = nomos_result
        if spatha_result is not None:
            vals["spatha_result"] = spatha_result
        if agros_result is not None:
            vals["agros_result"] = agros_result
        if trace_decision_id is not None:
            vals["trace_decision_id"] = trace_decision_id
        if trace_hash is not None:
            vals["trace_hash"] = trace_hash
        if arc_tx is not None:
            vals["arc_tx"] = arc_tx
        if status is not None:
            vals["status"] = status
        if completed:
            vals["completed_at"] = datetime.now(timezone.utc)
        if vals:
            await self.session.execute(
                update(KillSwitchEvent).where(KillSwitchEvent.id == event_id).values(**vals)
            )

    async def list_recent(self, limit: int = 20, user_id: Optional[str] = None) -> list[dict]:
        stmt = select(KillSwitchEvent).order_by(KillSwitchEvent.id.desc()).limit(limit)
        if user_id:
            stmt = stmt.where(KillSwitchEvent.user_id == user_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def get(self, event_id: int) -> Optional[dict]:
        row = (await self.session.execute(
            select(KillSwitchEvent).where(KillSwitchEvent.id == event_id)
        )).scalar_one_or_none()
        return _to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Feedback events (ERC-8004 reputation deltas)
# ---------------------------------------------------------------------------

class SQLFeedbackRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        user_id: str,
        event_type: str,
        delta,
        *,
        erc8004_id: Optional[int] = None,
        ref: Optional[dict] = None,
    ) -> int:
        row = FeedbackEvent(
            user_id=user_id,
            erc8004_id=erc8004_id,
            event_type=event_type,
            delta=delta,
            ref=ref or {},
        )
        self.session.add(row)
        await self.session.flush()
        return int(row.id)

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[dict]:
        rows = (await self.session.execute(
            select(FeedbackEvent)
            .where(FeedbackEvent.user_id == user_id)
            .order_by(FeedbackEvent.id.desc())
            .limit(limit)
        )).scalars().all()
        return [_to_dict(r) for r in rows]

    async def aggregate_by_user(self) -> dict[str, dict]:
        """Per-user reputation rollup: net delta, event count, and a per-type
        breakdown (for the leaderboard's reputation column)."""
        stmt = select(
            FeedbackEvent.user_id,
            FeedbackEvent.event_type,
            func.coalesce(func.sum(FeedbackEvent.delta), 0).label("total"),
            func.count(FeedbackEvent.id).label("n"),
        ).group_by(FeedbackEvent.user_id, FeedbackEvent.event_type)
        out: dict[str, dict] = {}
        for r in (await self.session.execute(stmt)).all():
            u = out.setdefault(r.user_id, {"total_delta": 0.0, "count": 0, "by_type": {}})
            total = float(r.total or 0)
            u["total_delta"] += total
            u["count"] += int(r.n)
            u["by_type"][r.event_type] = {"total_delta": total, "count": int(r.n)}
        return out

    async def mark_pushed(self, event_ids: list[int], onchain_tx: str) -> None:
        if not event_ids:
            return
        await self.session.execute(
            update(FeedbackEvent)
            .where(FeedbackEvent.id.in_(event_ids))
            .values(onchain_tx=onchain_tx)
        )


# ---------------------------------------------------------------------------
# User consents (signed EIP-712 records)
# ---------------------------------------------------------------------------

class SQLConsentRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        user_id: str,
        consent_type: str,
        version: str,
        signer_address: str,
        typed_data: dict,
        signature: str,
        onchain_tx: Optional[str] = None,
    ) -> dict:
        stmt = (
            pg_insert(UserConsent)
            .values(
                user_id=user_id,
                consent_type=consent_type,
                version=version,
                signer_address=signer_address,
                typed_data=typed_data,
                signature=signature,
                onchain_tx=onchain_tx,
            )
            .on_conflict_do_update(
                constraint="uq_user_consent",
                set_={
                    "signer_address": signer_address,
                    "typed_data": typed_data,
                    "signature": signature,
                    "onchain_tx": onchain_tx,
                },
            )
            .returning(UserConsent.id)
        )
        cid = (await self.session.execute(stmt)).scalar_one()
        row = (await self.session.execute(
            select(UserConsent).where(UserConsent.id == cid)
        )).scalar_one()
        return _to_dict(row)

    async def has_consent(self, user_id: str, consent_type: str, version: str) -> bool:
        row = (await self.session.execute(
            select(UserConsent.id).where(
                UserConsent.user_id == user_id,
                UserConsent.consent_type == consent_type,
                UserConsent.version == version,
            )
        )).scalar_one_or_none()
        return row is not None

    async def get(self, user_id: str, consent_type: str) -> Optional[dict]:
        row = (await self.session.execute(
            select(UserConsent)
            .where(
                UserConsent.user_id == user_id,
                UserConsent.consent_type == consent_type,
            )
            .order_by(UserConsent.id.desc())
            .limit(1)
        )).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def set_onchain_tx(self, consent_id: int, tx: str) -> None:
        await self.session.execute(
            update(UserConsent).where(UserConsent.id == consent_id).values(onchain_tx=tx)
        )

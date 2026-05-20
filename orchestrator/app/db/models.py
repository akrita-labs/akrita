"""
SQLAlchemy table definitions.

Every consequential piece of state lives here. Pydantic models in
`shared/models.py` are the wire format; these are the storage format.
Repositories under `orchestrator/app/repositories/` bridge the two.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.app.db.base import Base


class Decision(Base):
    """Every approved or rejected decision an agent submits."""

    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("agent_role", "decision_id", name="uq_decisions_agent_id"),
        UniqueConstraint("agent_role", "nonce", name="uq_decisions_agent_nonce"),
        Index("ix_decisions_ts_ms", "ts_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_role: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(32), nullable=False)
    nonce: Mapped[int] = mapped_column(Integer, nullable=False)
    ts_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rationale_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Trace(Base):
    """Trace-pipeline commit metadata. One row per approved decision."""

    __tablename__ = "traces"
    __table_args__ = (
        UniqueConstraint("decision_id", "agent_role", name="uq_traces_decision"),
        Index("ix_traces_trace_hash", "trace_hash"),
        Index("ix_traces_cid", "cid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_role: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    cid: Mapped[str | None] = mapped_column(String, nullable=True)
    arc_tx: Mapped[str | None] = mapped_column(String(66), nullable=True)
    arc_block: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Order(Base):
    """Polymarket order IDs, linked back to their pricing decision."""

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_market_status", "market_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    decision_pk: Mapped[int | None] = mapped_column(
        ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True
    )
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY / SELL
    price: Mapped[float] = mapped_column(Float, nullable=False)
    size: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    builder_code: Mapped[str | None] = mapped_column(String(66), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    decision = relationship("Decision", lazy="noload")


class Fill(Base):
    """Polymarket fills, dedup'd by Polygon (tx_hash, log_index)."""

    __tablename__ = "fills"
    __table_args__ = (
        UniqueConstraint("tx_hash", "log_index", name="uq_fills_tx_log"),
        Index("ix_fills_market_ts", "market_id", "ts_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    size: Mapped[float] = mapped_column(Float, nullable=False)
    builder_fee_usdc: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ts_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class HedgePosition(Base):
    """Open / closed hedge positions, identified by their venue-native id."""

    __tablename__ = "hedge_positions"
    __table_args__ = (
        UniqueConstraint("venue", "venue_position_id", name="uq_hedge_venue_id"),
        Index("ix_hedge_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    venue_position_id: Mapped[str] = mapped_column(String, nullable=False)
    decision_pk: Mapped[int | None] = mapped_column(
        ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True
    )
    instrument: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    size: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    margin_asset: Mapped[str] = mapped_column(String(16), nullable=False)
    margin_amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    pnl_usdc: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TreasuryAction(Base):
    """USYC subscribe/redeem + Gateway/CCTP transfers with settlement status."""

    __tablename__ = "treasury_actions"
    __table_args__ = (
        Index("ix_treasury_status_ts", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_pk: Mapped[int | None] = mapped_column(
        ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    src_chain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dst_chain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Balance(Base):
    """Most recent observed balance per (wallet, chain, token, source)."""

    __tablename__ = "balances"
    __table_args__ = (
        UniqueConstraint(
            "wallet_addr", "chain", "token", "source", name="uq_balance_key"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_role: Mapped[str] = mapped_column(String(32), nullable=False)
    wallet_addr: Mapped[str] = mapped_column(String(42), nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    token: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(38, 18), nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="chain")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InventorySnapshot(Base):
    """Per-market exposure series. New row per fill/snapshot tick."""

    __tablename__ = "inventory_snapshots"
    __table_args__ = (
        Index("ix_inventory_market_ts", "market_id", "snapshot_ts_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    net_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    long_size: Mapped[float] = mapped_column(Float, nullable=False)
    short_size: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot_ts_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AdapterEvent(Base):
    """Raw events from external adapters. Audit + reprocessing source of truth."""

    __tablename__ = "adapter_events"
    __table_args__ = (
        Index("ix_adapter_events_recv", "adapter", "received_at"),
        Index(
            "ix_adapter_events_external",
            "adapter",
            "external_id",
            unique=True,
            postgresql_where="external_id IS NOT NULL",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    adapter: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

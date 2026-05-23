"""
SQLAlchemy table definitions.

Every consequential piece of state lives here. Pydantic models in
`shared/models.py` are the wire format; these are the storage format.
Repositories under `orchestrator/app/repositories/` bridge the two.

Multi-tenant: identity tables (users, sessions, session_keys,
builder_profiles, agent_instances) own the per-person config; every
execution table carries `user_id` (and `agent_instance_id` on
decisions/traces) for row-level isolation. UUIDs are stored as
String(36) so they pass through JSON / the decision envelope unchanged.
"""
from __future__ import annotations

import uuid
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
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Identity / tenancy
# ---------------------------------------------------------------------------

class User(Base):
    """A person operating their own agents. Identity = a smart-account
    (Circle Modular Wallet) address authenticated via passkey."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    handle: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    msca_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    passkey_credential_id: Mapped[str | None] = mapped_column(String, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    jurisdiction_declared: Mapped[str | None] = mapped_column(String(2), nullable=True)
    jurisdiction_ip_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    is_us_person: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Session(Base):
    """Opaque server-side session; the cookie carries the raw token,
    we store only its sha256."""

    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SessionKey(Base):
    """A scoped delegated signing key the user installs on their smart
    account so AKRITA can sign fund-moving actions autonomously."""

    __tablename__ = "session_keys"
    __table_args__ = (Index("ix_session_keys_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_key_address: Mapped[str] = mapped_column(String(42), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    installed_tx: Mapped[str | None] = mapped_column(String(66), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BuilderProfile(Base):
    """Per-user Polymarket builder code + encrypted CLOB creds + on-chain
    agentId allocation for BuilderRegistry/TraceRegistry."""

    __tablename__ = "builder_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_builder_profiles_user"),
        UniqueConstraint("builder_code", name="uq_builder_profiles_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    builder_code: Mapped[str] = mapped_column(String(66), nullable=False)
    onchain_agent_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    registration_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    registration_tx: Mapped[str | None] = mapped_column(String(66), nullable=True)
    poly_api_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    poly_api_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    poly_api_passphrase_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    poly_signer_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    poly_collateral_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AgentInstance(Base):
    """A user-owned configured instance of an archetype (nomos/spatha/agros).
    All per-instance tunables live in `params` (JSONB) for forward-compat."""

    __tablename__ = "agent_instances"
    __table_args__ = (
        UniqueConstraint("user_id", "archetype", "name", name="uq_agent_instances_name"),
        Index("ix_agent_instances_arch_enabled", "archetype", "enabled"),
        Index("ix_agent_instances_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    archetype: Mapped[str] = mapped_column(String(16), nullable=False)  # nomos|spatha|agros
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="default")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kill_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Execution tables (each scoped by user_id)
# ---------------------------------------------------------------------------

class Decision(Base):
    """Every approved or rejected decision an agent submits."""

    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("agent_instance_id", "decision_id", name="uq_decisions_instance_id"),
        UniqueConstraint("agent_instance_id", "nonce", name="uq_decisions_instance_nonce"),
        Index("ix_decisions_user_ts", "user_id", "ts_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agent_instance_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_instances.id", ondelete="SET NULL"), nullable=True
    )
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
        UniqueConstraint("agent_instance_id", "decision_id", name="uq_traces_instance_decision"),
        Index("ix_traces_trace_hash", "trace_hash"),
        Index("ix_traces_cid", "cid"),
        Index("ix_traces_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agent_instance_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_instances.id", ondelete="SET NULL"), nullable=True
    )
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
        Index("ix_orders_user_status", "user_id", "status"),
        Index("ix_orders_market_status", "market_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
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
        Index("ix_fills_user_ts", "user_id", "ts_ms"),
        Index("ix_fills_market_ts", "market_id", "ts_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
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
        Index("ix_hedge_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
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
        Index("ix_treasury_user_ts", "user_id", "created_at"),
        Index("ix_treasury_status_ts", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
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
    """Most recent observed balance per (user, wallet, chain, token, source)."""

    __tablename__ = "balances"
    __table_args__ = (
        UniqueConstraint(
            "wallet_addr", "chain", "token", "source", name="uq_balance_key"
        ),
        Index("ix_balances_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
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
    """Per-(user, market) exposure series. New row per fill/snapshot tick."""

    __tablename__ = "inventory_snapshots"
    __table_args__ = (
        Index("ix_inventory_user_market_ts", "user_id", "market_id", "snapshot_ts_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    net_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    long_size: Mapped[float] = mapped_column(Float, nullable=False)
    short_size: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot_ts_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AdapterEvent(Base):
    """Raw events from external adapters. Audit + reprocessing source of truth.
    `user_id` nullable — some adapter events are global/infra."""

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
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    adapter: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Platform tables (catalog + cross-cutting lifecycle events)
# ---------------------------------------------------------------------------

class Template(Base):
    """A named bundle of NOMOS/SPATHA tunables + an AGROS tier. Users pick a
    template to seed their agent_instances. Global catalog (no user_id)."""

    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    nomos_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    spatha_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    agros_tier: Mapped[str] = mapped_column(String(1), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KillSwitchEvent(Base):
    """One row per kill-switch trip: who/what triggered it and the per-agent
    unwind results, plus the anchoring trace + on-chain tx for auditability."""

    __tablename__ = "kill_switch_events"
    __table_args__ = (Index("ix_kill_switch_user_ts", "user_id", "triggered_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    trigger_source: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    nomos_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    spatha_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    agros_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    trace_decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    arc_tx: Mapped[str | None] = mapped_column(String(66), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FeedbackEvent(Base):
    """Reputation deltas (per ERC-8004) buffered before being pushed on-chain.
    `delta` is signed; `ref` links back to the source decision/trace/fill."""

    __tablename__ = "feedback_events"
    __table_args__ = (Index("ix_feedback_user_ts", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    erc8004_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    delta: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    onchain_tx: Mapped[str | None] = mapped_column(String(66), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserConsent(Base):
    """A signed (EIP-712) consent record — one per (user, consent_type, version).
    Stores the typed data + signature so the consent is independently verifiable."""

    __tablename__ = "user_consents"
    __table_args__ = (
        UniqueConstraint("user_id", "consent_type", "version", name="uq_user_consent"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    consent_type: Mapped[str] = mapped_column(String(48), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    signer_address: Mapped[str] = mapped_column(String(42), nullable=False)
    typed_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    signature: Mapped[str] = mapped_column(String(132), nullable=False)
    onchain_tx: Mapped[str | None] = mapped_column(String(66), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

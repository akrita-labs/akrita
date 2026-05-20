"""Initial AKRITA schema — decisions, traces, orders, fills, hedge_positions,
treasury_actions, balances, inventory_snapshots, adapter_events.

Revision ID: 0001
Revises:
Create Date: 2026-05-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("decision_id", sa.Integer, nullable=False),
        sa.Column("agent_role", sa.String(32), nullable=False),
        sa.Column("decision_type", sa.String(32), nullable=False),
        sa.Column("nonce", sa.Integer, nullable=False),
        sa.Column("ts_ms", sa.BigInteger, nullable=False),
        sa.Column("rationale_hash", sa.String(66), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("rejection_reason", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("agent_role", "decision_id", name="uq_decisions_agent_id"),
        sa.UniqueConstraint("agent_role", "nonce", name="uq_decisions_agent_nonce"),
    )
    op.create_index("ix_decisions_ts_ms", "decisions", ["ts_ms"])

    op.create_table(
        "traces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("decision_id", sa.Integer, nullable=False),
        sa.Column("agent_role", sa.String(32), nullable=False),
        sa.Column("trace_hash", sa.String(66), nullable=False),
        sa.Column("cid", sa.String, nullable=True),
        sa.Column("arc_tx", sa.String(66), nullable=True),
        sa.Column("arc_block", sa.BigInteger, nullable=True),
        sa.Column("body", JSONB, nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("decision_id", "agent_role", name="uq_traces_decision"),
    )
    op.create_index("ix_traces_trace_hash", "traces", ["trace_hash"])
    op.create_index("ix_traces_cid", "traces", ["cid"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String, nullable=False, unique=True),
        sa.Column("decision_pk", sa.Integer, sa.ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("market_id", sa.String, nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("price", sa.Float, nullable=False),
        sa.Column("size", sa.Float, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("builder_code", sa.String(66), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orders_market_status", "orders", ["market_id", "status"])

    op.create_table(
        "fills",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tx_hash", sa.String(66), nullable=False),
        sa.Column("log_index", sa.Integer, nullable=False),
        sa.Column("order_id", sa.String, nullable=True),
        sa.Column("market_id", sa.String, nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("price", sa.Float, nullable=False),
        sa.Column("size", sa.Float, nullable=False),
        sa.Column("builder_fee_usdc", sa.Float, nullable=False, server_default="0"),
        sa.Column("ts_ms", sa.BigInteger, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tx_hash", "log_index", name="uq_fills_tx_log"),
    )
    op.create_index("ix_fills_market_ts", "fills", ["market_id", "ts_ms"])

    op.create_table(
        "hedge_positions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("venue_position_id", sa.String, nullable=False),
        sa.Column("decision_pk", sa.Integer, sa.ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("instrument", sa.String(64), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("size", sa.Float, nullable=False),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("margin_asset", sa.String(16), nullable=False),
        sa.Column("margin_amount", sa.Float, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("pnl_usdc", sa.Float, nullable=False, server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("venue", "venue_position_id", name="uq_hedge_venue_id"),
    )
    op.create_index("ix_hedge_status", "hedge_positions", ["status"])

    op.create_table(
        "treasury_actions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("decision_pk", sa.Integer, sa.ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("src_chain", sa.String(32), nullable=True),
        sa.Column("dst_chain", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("tx_hash", sa.String(66), nullable=True),
        sa.Column("external_ref", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_treasury_status_ts", "treasury_actions", ["status", "created_at"])

    op.create_table(
        "balances",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("wallet_role", sa.String(32), nullable=False),
        sa.Column("wallet_addr", sa.String(42), nullable=False),
        sa.Column("chain", sa.String(32), nullable=False),
        sa.Column("token", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=False, server_default="0"),
        sa.Column("source", sa.String(32), nullable=False, server_default="chain"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("wallet_addr", "chain", "token", "source", name="uq_balance_key"),
    )

    op.create_table(
        "inventory_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.String, nullable=False),
        sa.Column("net_exposure", sa.Float, nullable=False),
        sa.Column("long_size", sa.Float, nullable=False),
        sa.Column("short_size", sa.Float, nullable=False),
        sa.Column("snapshot_ts_ms", sa.BigInteger, nullable=False),
    )
    op.create_index("ix_inventory_market_ts", "inventory_snapshots", ["market_id", "snapshot_ts_ms"])

    op.create_table(
        "adapter_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("adapter", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String, nullable=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_adapter_events_recv", "adapter_events", ["adapter", "received_at"])
    op.create_index(
        "ix_adapter_events_external",
        "adapter_events",
        ["adapter", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("adapter_events")
    op.drop_table("inventory_snapshots")
    op.drop_table("balances")
    op.drop_table("treasury_actions")
    op.drop_table("hedge_positions")
    op.drop_table("fills")
    op.drop_table("orders")
    op.drop_table("traces")
    op.drop_table("decisions")

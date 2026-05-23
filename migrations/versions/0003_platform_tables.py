"""Platform tables: templates catalog, kill-switch events, feedback (ERC-8004)
events, and signed user consents; + jurisdiction / US-person columns on users.
Seeds the three default agent templates idempotently.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-23
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_NOW = sa.text("now()")

# Deterministic template ids (stable across environments for idempotent seeds).
_TEMPLATE_CONSERVATIVE = "00000000-0000-0000-0000-0000000c0001"
_TEMPLATE_BALANCED = "00000000-0000-0000-0000-0000000c0002"
_TEMPLATE_AGGRESSIVE = "00000000-0000-0000-0000-0000000c0003"

# Seed values. NOTE: conservative offset 0.75 is pending a NOMOS sim
# degeneration check; tune to 0.65 if it does-not-trade.
_TEMPLATES = [
    {
        "id": _TEMPLATE_CONSERVATIVE,
        "key": "conservative_king",
        "display_name": "The Conservative King",
        "agros_tier": "A",
        "is_default": False,
        "nomos_params": {
            "quote_spread_bps_offset_to_max_spread": 0.75,
            "inventory_target_pct": 0.5,
            "max_position_per_market_usd": 50,
            "daily_loss_limit_usd": 20,
            "market_whitelist_tags": ["crypto", "sports"],
        },
        "spatha_params": {
            "hedge_band_risk_aversion": 0.5,
            "hedge_underlying_whitelist": ["BTC", "ETH"],
            "leverage_cap": 2,
            "kill_switch_funding_apr_pct": 200,
        },
    },
    {
        "id": _TEMPLATE_BALANCED,
        "key": "balanced_counsel",
        "display_name": "The Balanced Counsel",
        "agros_tier": "B",
        "is_default": True,
        "nomos_params": {
            "quote_spread_bps_offset_to_max_spread": 0.5,
            "inventory_target_pct": 0.5,
            "max_position_per_market_usd": 50,
            "daily_loss_limit_usd": 20,
            "market_whitelist_tags": ["crypto", "sports"],
        },
        "spatha_params": {
            "hedge_band_risk_aversion": 1.0,
            "hedge_underlying_whitelist": ["BTC", "ETH", "SOL"],
            "leverage_cap": 3,
            "kill_switch_funding_apr_pct": 200,
        },
    },
    {
        "id": _TEMPLATE_AGGRESSIVE,
        "key": "aggressive_sovereign",
        "display_name": "The Aggressive Sovereign",
        "agros_tier": "C",
        "is_default": False,
        "nomos_params": {
            "quote_spread_bps_offset_to_max_spread": 0.25,
            "inventory_target_pct": 0.5,
            "max_position_per_market_usd": 100,
            "daily_loss_limit_usd": 50,
            "market_whitelist_tags": ["crypto", "sports"],
        },
        "spatha_params": {
            "hedge_band_risk_aversion": 2.0,
            "hedge_underlying_whitelist": ["BTC", "ETH", "SOL"],
            "leverage_cap": 5,
            "kill_switch_funding_apr_pct": 300,
        },
    },
]


def upgrade() -> None:
    # ---- 1. user jurisdiction / US-person columns --------------------------
    op.add_column("users", sa.Column("jurisdiction_declared", sa.String(2), nullable=True))
    op.add_column("users", sa.Column("jurisdiction_ip_country", sa.String(2), nullable=True))
    op.add_column(
        "users",
        sa.Column("is_us_person", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    # ---- 2. templates ------------------------------------------------------
    op.create_table(
        "templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(32), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("nomos_params", JSONB, nullable=False),
        sa.Column("spatha_params", JSONB, nullable=False),
        sa.Column("agros_tier", sa.String(1), nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    )

    # ---- 3. kill_switch_events --------------------------------------------
    op.create_table(
        "kill_switch_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger_source", sa.String(32), nullable=False),
        sa.Column("trigger_detail", JSONB, nullable=False, server_default="{}"),
        sa.Column("nomos_result", JSONB, nullable=False, server_default="{}"),
        sa.Column("spatha_result", JSONB, nullable=False, server_default="{}"),
        sa.Column("agros_result", JSONB, nullable=False, server_default="{}"),
        sa.Column("trace_decision_id", sa.Integer, nullable=True),
        sa.Column("trace_hash", sa.String(66), nullable=True),
        sa.Column("arc_tx", sa.String(66), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_kill_switch_user_ts", "kill_switch_events", ["user_id", "triggered_at"])

    # ---- 4. feedback_events -----------------------------------------------
    op.create_table(
        "feedback_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("erc8004_id", sa.BigInteger, nullable=True),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("delta", sa.Numeric(20, 6), nullable=False),
        sa.Column("ref", JSONB, nullable=False, server_default="{}"),
        sa.Column("onchain_tx", sa.String(66), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    )
    op.create_index("ix_feedback_user_ts", "feedback_events", ["user_id", "created_at"])

    # ---- 5. user_consents --------------------------------------------------
    op.create_table(
        "user_consents",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consent_type", sa.String(48), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("signer_address", sa.String(42), nullable=False),
        sa.Column("typed_data", JSONB, nullable=False),
        sa.Column("signature", sa.String(132), nullable=False),
        sa.Column("onchain_tx", sa.String(66), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("user_id", "consent_type", "version", name="uq_user_consent"),
    )

    # ---- 6. seed default templates (idempotent on key) --------------------
    seed = sa.text(
        "INSERT INTO templates "
        "(id, key, display_name, nomos_params, spatha_params, agros_tier, is_default) "
        "VALUES (:id, :key, :display_name, "
        "CAST(:nomos_params AS jsonb), CAST(:spatha_params AS jsonb), "
        ":agros_tier, :is_default) "
        "ON CONFLICT (key) DO NOTHING"
    )
    for t in _TEMPLATES:
        op.execute(
            seed.bindparams(
                id=t["id"],
                key=t["key"],
                display_name=t["display_name"],
                nomos_params=json.dumps(t["nomos_params"]),
                spatha_params=json.dumps(t["spatha_params"]),
                agros_tier=t["agros_tier"],
                is_default=t["is_default"],
            )
        )


def downgrade() -> None:
    op.drop_table("user_consents")

    op.drop_index("ix_feedback_user_ts", table_name="feedback_events")
    op.drop_table("feedback_events")

    op.drop_index("ix_kill_switch_user_ts", table_name="kill_switch_events")
    op.drop_table("kill_switch_events")

    op.drop_table("templates")

    op.drop_column("users", "is_us_person")
    op.drop_column("users", "jurisdiction_ip_country")
    op.drop_column("users", "jurisdiction_declared")

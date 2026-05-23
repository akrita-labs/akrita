"""Multi-tenant: users/sessions/session_keys/builder_profiles/agent_instances,
+ user_id (and agent_instance_id on decisions/traces) on every execution
table, with a "system" user backfill for existing single-tenant rows.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Deterministic system-tenant IDs (own the pre-existing single-tenant rows).
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"
SYSTEM_INSTANCE = {
    "nomos": "00000000-0000-0000-0000-0000000a0001",
    "spatha": "00000000-0000-0000-0000-0000000a0002",
    "agros": "00000000-0000-0000-0000-0000000a0003",
}

_NOW = sa.text("now()")
_EXEC_TABLES = [
    "decisions", "traces", "orders", "fills", "hedge_positions",
    "treasury_actions", "balances", "inventory_snapshots",
]


def upgrade() -> None:
    # ---- 1. identity tables ------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("handle", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column("msca_address", sa.String(42), nullable=True),
        sa.Column("passkey_credential_id", sa.String, nullable=True),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    )
    op.create_index("ix_sessions_user", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires", "sessions", ["expires_at"])
    op.create_table(
        "session_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_key_address", sa.String(42), nullable=False),
        sa.Column("scope", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("installed_tx", sa.String(66), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    )
    op.create_index("ix_session_keys_user", "session_keys", ["user_id"])
    op.create_table(
        "builder_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("builder_code", sa.String(66), nullable=False),
        sa.Column("onchain_agent_id", sa.BigInteger, nullable=True, unique=True),
        sa.Column("registration_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("registration_tx", sa.String(66), nullable=True),
        sa.Column("poly_api_key_enc", sa.LargeBinary, nullable=True),
        sa.Column("poly_api_secret_enc", sa.LargeBinary, nullable=True),
        sa.Column("poly_api_passphrase_enc", sa.LargeBinary, nullable=True),
        sa.Column("poly_signer_enc", sa.LargeBinary, nullable=True),
        sa.Column("poly_collateral_ready", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("user_id", name="uq_builder_profiles_user"),
        sa.UniqueConstraint("builder_code", name="uq_builder_profiles_code"),
    )
    op.create_table(
        "agent_instances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("archetype", sa.String(16), nullable=False),
        sa.Column("name", sa.String(120), nullable=False, server_default="default"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("kill_switch", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("params", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("user_id", "archetype", "name", name="uq_agent_instances_name"),
    )
    op.create_index("ix_agent_instances_arch_enabled", "agent_instances", ["archetype", "enabled"])
    op.create_index("ix_agent_instances_user", "agent_instances", ["user_id"])

    # ---- 2. seed system user + system instances ----------------------------
    op.execute(
        sa.text(
            "INSERT INTO users (id, handle, display_name, is_system, is_active) "
            "VALUES (:id, 'system', 'System (pre-multitenant)', true, true)"
        ).bindparams(id=SYSTEM_USER_ID)
    )
    for archetype, iid in SYSTEM_INSTANCE.items():
        op.execute(
            sa.text(
                "INSERT INTO agent_instances (id, user_id, archetype, name, enabled) "
                "VALUES (:id, :uid, :arch, 'system', true)"
            ).bindparams(id=iid, uid=SYSTEM_USER_ID, arch=archetype)
        )

    # ---- 3. add user_id to exec tables (nullable -> backfill -> not null) ---
    for tbl in _EXEC_TABLES:
        nullable_default = tbl == "adapter_events"  # handled separately below
        op.add_column(tbl, sa.Column("user_id", sa.String(36), nullable=True))
        op.execute(sa.text(f"UPDATE {tbl} SET user_id = :uid").bindparams(uid=SYSTEM_USER_ID))
        op.alter_column(tbl, "user_id", nullable=False)
        op.create_foreign_key(
            f"fk_{tbl}_user", tbl, "users", ["user_id"], ["id"], ondelete="CASCADE"
        )

    # adapter_events: user_id stays nullable (infra events have no owner)
    op.add_column("adapter_events", sa.Column("user_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_adapter_events_user", "adapter_events", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )

    # ---- 4. agent_instance_id on decisions + traces (backfill by role) ------
    for tbl in ("decisions", "traces"):
        op.add_column(tbl, sa.Column("agent_instance_id", sa.String(36), nullable=True))
        for archetype, iid in SYSTEM_INSTANCE.items():
            op.execute(
                sa.text(
                    f"UPDATE {tbl} SET agent_instance_id = :iid WHERE agent_role = :role"
                ).bindparams(iid=iid, role=archetype)
            )
        op.create_foreign_key(
            f"fk_{tbl}_instance", tbl, "agent_instances",
            ["agent_instance_id"], ["id"], ondelete="SET NULL",
        )

    # ---- 5. swap unique constraints / indexes to instance-scoped -----------
    op.drop_constraint("uq_decisions_agent_id", "decisions", type_="unique")
    op.drop_constraint("uq_decisions_agent_nonce", "decisions", type_="unique")
    op.create_unique_constraint("uq_decisions_instance_id", "decisions", ["agent_instance_id", "decision_id"])
    op.create_unique_constraint("uq_decisions_instance_nonce", "decisions", ["agent_instance_id", "nonce"])
    op.drop_index("ix_decisions_ts_ms", table_name="decisions")
    op.create_index("ix_decisions_user_ts", "decisions", ["user_id", "ts_ms"])

    op.drop_constraint("uq_traces_decision", "traces", type_="unique")
    op.create_unique_constraint("uq_traces_instance_decision", "traces", ["agent_instance_id", "decision_id"])
    op.create_index("ix_traces_user", "traces", ["user_id"])

    # ---- 6. per-table user indexes ----------------------------------------
    op.create_index("ix_orders_user_status", "orders", ["user_id", "status"])
    op.create_index("ix_fills_user_ts", "fills", ["user_id", "ts_ms"])
    op.create_index("ix_hedge_user_status", "hedge_positions", ["user_id", "status"])
    op.create_index("ix_treasury_user_ts", "treasury_actions", ["user_id", "created_at"])
    op.create_index("ix_balances_user", "balances", ["user_id"])
    op.create_index("ix_inventory_user_market_ts", "inventory_snapshots", ["user_id", "market_id", "snapshot_ts_ms"])


def downgrade() -> None:
    op.drop_index("ix_inventory_user_market_ts", table_name="inventory_snapshots")
    op.drop_index("ix_balances_user", table_name="balances")
    op.drop_index("ix_treasury_user_ts", table_name="treasury_actions")
    op.drop_index("ix_hedge_user_status", table_name="hedge_positions")
    op.drop_index("ix_fills_user_ts", table_name="fills")
    op.drop_index("ix_orders_user_status", table_name="orders")

    op.drop_index("ix_traces_user", table_name="traces")
    op.drop_constraint("uq_traces_instance_decision", "traces", type_="unique")
    op.create_unique_constraint("uq_traces_decision", "traces", ["decision_id", "agent_role"])

    op.drop_index("ix_decisions_user_ts", table_name="decisions")
    op.create_index("ix_decisions_ts_ms", "decisions", ["ts_ms"])
    op.drop_constraint("uq_decisions_instance_nonce", "decisions", type_="unique")
    op.drop_constraint("uq_decisions_instance_id", "decisions", type_="unique")
    op.create_unique_constraint("uq_decisions_agent_nonce", "decisions", ["agent_role", "nonce"])
    op.create_unique_constraint("uq_decisions_agent_id", "decisions", ["agent_role", "decision_id"])

    for tbl in ("decisions", "traces"):
        op.drop_constraint(f"fk_{tbl}_instance", tbl, type_="foreignkey")
        op.drop_column(tbl, "agent_instance_id")

    op.drop_constraint("fk_adapter_events_user", "adapter_events", type_="foreignkey")
    op.drop_column("adapter_events", "user_id")
    for tbl in _EXEC_TABLES:
        op.drop_constraint(f"fk_{tbl}_user", tbl, type_="foreignkey")
        op.drop_column(tbl, "user_id")

    op.drop_table("agent_instances")
    op.drop_table("builder_profiles")
    op.drop_table("session_keys")
    op.drop_table("sessions")
    op.drop_table("users")

"""
Repository layer.

Protocols in `base.py` define the surface every persistent collection
exposes. `sqlalchemy.py` is the live implementation (Postgres via async
SQLAlchemy). Test-only in-memory implementations can go alongside if
needed.

Each repository takes an `AsyncSession` in its constructor and is
session-scoped. Higher layers (state.py, FastAPI dependencies) own
the session lifecycle and commit/rollback.
"""
from orchestrator.app.repositories.base import (
    AdapterEventRepo,
    BalanceRepo,
    DecisionRepo,
    FillRepo,
    HedgePositionRepo,
    InventoryRepo,
    OrderRepo,
    TraceRepo,
    TreasuryActionRepo,
)
from orchestrator.app.repositories.sqlalchemy import (
    SQLAdapterEventRepo,
    SQLBalanceRepo,
    SQLDecisionRepo,
    SQLFillRepo,
    SQLHedgePositionRepo,
    SQLInventoryRepo,
    SQLOrderRepo,
    SQLTraceRepo,
    SQLTreasuryActionRepo,
)

__all__ = [
    # Protocols
    "AdapterEventRepo",
    "BalanceRepo",
    "DecisionRepo",
    "FillRepo",
    "HedgePositionRepo",
    "InventoryRepo",
    "OrderRepo",
    "TraceRepo",
    "TreasuryActionRepo",
    # SQLAlchemy impls
    "SQLAdapterEventRepo",
    "SQLBalanceRepo",
    "SQLDecisionRepo",
    "SQLFillRepo",
    "SQLHedgePositionRepo",
    "SQLInventoryRepo",
    "SQLOrderRepo",
    "SQLTraceRepo",
    "SQLTreasuryActionRepo",
]

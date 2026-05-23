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
    ConsentRepo,
    DecisionRepo,
    FeedbackRepo,
    FillRepo,
    HedgePositionRepo,
    InventoryRepo,
    KillSwitchRepo,
    OrderRepo,
    TemplateRepo,
    TraceRepo,
    TreasuryActionRepo,
)
from orchestrator.app.repositories.sqlalchemy import (
    SQLAdapterEventRepo,
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

__all__ = [
    # Protocols
    "AdapterEventRepo",
    "BalanceRepo",
    "ConsentRepo",
    "DecisionRepo",
    "FeedbackRepo",
    "FillRepo",
    "HedgePositionRepo",
    "InventoryRepo",
    "KillSwitchRepo",
    "OrderRepo",
    "TemplateRepo",
    "TraceRepo",
    "TreasuryActionRepo",
    # SQLAlchemy impls
    "SQLAdapterEventRepo",
    "SQLAgentInstanceRepo",
    "SQLBalanceRepo",
    "SQLBuilderProfileRepo",
    "SQLConsentRepo",
    "SQLDecisionRepo",
    "SQLFeedbackRepo",
    "SQLFillRepo",
    "SQLHedgePositionRepo",
    "SQLInventoryRepo",
    "SQLKillSwitchRepo",
    "SQLOrderRepo",
    "SQLTemplateRepo",
    "SQLTraceRepo",
    "SQLTreasuryActionRepo",
    "SQLUserRepo",
]

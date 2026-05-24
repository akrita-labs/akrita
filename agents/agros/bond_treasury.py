"""
AGROS — bond-pool treasury for the Rugpull Oracle (pure planners).

AGROS keeps the Arc bond pool able to cover active bonds, funding shortfalls
cross-chain via Circle Gateway (GatewayReal.transfer) and parking surplus in
USYC for yield between events. These are pure decision functions; the orchestrator
executes the resulting plan through the existing Gateway / USYC adapters.
"""
from __future__ import annotations


def bond_funding_plan(
    arc_bond_balance_usdc: float,
    active_bond_notional_usdc: float,
    *,
    target_coverage: float = 1.0,
    source_chain: str = "",
) -> dict:
    """Decide whether to pull USDC to Arc (via Gateway) to cover active bonds.

    `target` is the USDC the Arc pool should hold to back open bonds; a shortfall
    triggers a Gateway inflow from `source_chain` (when configured).
    """
    target = max(0.0, active_bond_notional_usdc) * max(1.0, target_coverage)
    shortfall = max(0.0, target - arc_bond_balance_usdc)
    return {
        "target_usdc": target,
        "shortfall_usdc": shortfall,
        "action": "gateway_inflow" if (shortfall > 0 and source_chain) else "none",
        "source_chain": source_chain,
    }


def idle_to_usyc(arc_bond_balance_usdc: float, target_usdc: float, *, min_subscribe: float = 10.0) -> float:
    """USDC surplus over the bond target to park in USYC (0 if below min_subscribe)."""
    surplus = arc_bond_balance_usdc - target_usdc
    return max(0.0, surplus) if surplus >= min_subscribe else 0.0

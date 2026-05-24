"""
SPATHA — claim-exposure hedging for the Rugpull Oracle (pure planner).

When AKRITA itself takes directional exposure on an issued claim (e.g. backing
its own rug prediction), SPATHA hedges it on Hyperliquid. This reuses the same
no-transaction-band / side / leverage helpers as the original hedger; the
orchestrator executes the plan through HyperliquidReal.
"""
from __future__ import annotations

from agents.spatha.hedge import clamp_leverage, hedge_side_for, should_hedge


def claim_hedge_plan(
    token: str,
    net_exposure_usd: float,
    *,
    band_usd: float,
    leverage_cap: float = 3.0,
    leverage: float = 2.0,
) -> dict:
    """Hedge plan for directional exposure on a claim token.

    Returns `{"action": "none"}` inside the no-transaction band; otherwise an
    open order on `{TOKEN}-PERP` sized off the exposure, opposite the drift.
    """
    if not should_hedge(net_exposure_usd, band_usd):
        return {"action": "none", "token": token.upper()}
    lev = clamp_leverage(leverage, leverage_cap)
    return {
        "action": "open",
        "token": token.upper(),
        "instrument": f"{token.upper()}-PERP",
        "side": hedge_side_for(net_exposure_usd),
        "size": abs(net_exposure_usd) / 1000.0,
        "leverage": lev,
        "margin": abs(net_exposure_usd) * 0.5 / lev,
        "venue": "hyperliquid",
    }

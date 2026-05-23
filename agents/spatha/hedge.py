"""
SPATHA — Pure hedge math.

Import-safe (no network, no orchestrator, no settings). Everything here is a
deterministic function of its arguments so it can be unit-tested in isolation
and reasoned about in a trace.

The headline primitive is the Whalley-Wilmott *no-transaction band*: under
proportional transaction costs it is optimal to leave a delta position
un-hedged while it sits inside a band around the target, and only re-hedge when
it breaches the band. A wider band trades a little residual delta risk for far
fewer (cost-bearing) hedge legs; a narrower band hugs delta-neutral at the
expense of churn. The half-width shrinks as risk-aversion ``a`` rises.
"""
from __future__ import annotations

from shared.params import max_funding_bps_hr


def no_transaction_band(a: float, cost_rate: float, gamma: float, price: float) -> float:
    """Whalley-Wilmott no-transaction band half-width (in USD of exposure).

        w = (3 * cost_rate * gamma**2 * price / (2 * a)) ** (1/3)

    where ``a`` is the user's risk-aversion, ``cost_rate`` the round-trip
    proportional trading cost (slippage + taker fee, as a fraction), ``gamma``
    the option-equivalent convexity of the book, and ``price`` the reference
    notional. Smaller ``a`` -> wider band (more tolerant of drift); larger
    ``a`` -> tighter band (re-hedges sooner).

    All inputs must be strictly positive; returns 0.0 otherwise so the caller
    degrades to "always hedge on any exposure" rather than crashing.
    """
    if a <= 0 or cost_rate <= 0 or gamma <= 0 or price <= 0:
        return 0.0
    return (3.0 * cost_rate * gamma**2 * price / (2.0 * a)) ** (1.0 / 3.0)


def should_hedge(net_exposure: float, band_usd: float) -> bool:
    """True when |net_exposure| has breached the no-transaction band."""
    return abs(net_exposure) > band_usd


def funding_ceiling_ok(current_funding_bps_per_hr: float, a: float) -> bool:
    """True when the venue's hourly funding is at or below the a-scaled ceiling.

    The ceiling is an INTERNAL guardrail (never a user field): a more
    risk-averse operator (larger ``a``) tolerates paying more funding to stay
    hedged, capped at 100 bps/hr. See ``max_funding_bps_hr``.
    """
    return current_funding_bps_per_hr <= max_funding_bps_hr(a)


def kill_switch_funding_tripped(
    funding_apr_pct: float, kill_switch_funding_apr_pct: float
) -> bool:
    """True when annualized funding has tripped the user's kill switch."""
    return funding_apr_pct > kill_switch_funding_apr_pct


def hedge_side_for(net_exposure: float) -> str:
    """Direction of the hedge leg.

    Positive net exposure (net long the underlying via the PM book) is
    neutralized by SHORTING the proxy; negative exposure by going LONG.
    """
    return "short" if net_exposure > 0 else "long"


def clamp_leverage(requested: float, leverage_cap: float) -> float:
    """Clamp requested leverage into ``[1.0, leverage_cap]``."""
    return max(1.0, min(requested, leverage_cap))

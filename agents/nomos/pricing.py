"""
NOMOS — pure pricing functions.

This module is the depurated, fully unit-testable core of NOMOS. It is
deliberately import-safe: no network, no IO, no global state, no side effects
at import or call time. Every function is deterministic — same inputs always
produce the same outputs — so the offline simulator and the orchestrator tests
can exercise the full quote surface without touching Polymarket.

The user-facing knobs live in `shared.params.NomosParams`; the non-tunable
constants (GAMMA, MIN_SPREAD, MAX_LOSS_PER_MARKET_PCT) live alongside them and
are imported here so the mapping has a single source of truth.
"""
from __future__ import annotations

from shared.params import GAMMA, MAX_LOSS_PER_MARKET_PCT, MIN_SPREAD, NomosParams

# Tradeable price bounds in probability units. Quotes are clamped here so we
# never rest an order at a degenerate 0/1 boundary.
PRICE_FLOOR = 0.02
PRICE_CEIL = 0.98


def compute_quote(
    mid: float,
    max_spread: float,
    inventory_ratio: float,
    params: NomosParams,
) -> dict:
    """Two-sided quote around a reservation price tilted by inventory.

    Mapping (deterministic):
      half_spread = quote_spread_bps_offset_to_max_spread * (max_spread / 2)
      r           = mid - (inventory_ratio - inventory_target_pct) * GAMMA * max_spread
      bid         = r - half_spread
      ask         = r + half_spread

    The reservation price `r` tilts away from the side we are already long: if
    inventory_ratio is above target we shade `r` down (encouraging sells); below
    target we shade it up. GAMMA is internal and never user-tunable.

    bid/ask are clamped to [PRICE_FLOOR, PRICE_CEIL] and the spread is widened
    symmetrically (about the clamped midpoint) if it would fall below MIN_SPREAD.

    Returns {"bid", "ask", "size", "confidence"}:
      - size       — USD cap from max_position_per_market_usd (treated as a cap).
      - confidence  — in (0, 1]; higher when the quoted spread is tight relative
        to the available max_spread (a tighter quote = more conviction).
    """
    offset = params.quote_spread_bps_offset_to_max_spread
    half_spread = offset * (max_spread / 2.0)

    # Inventory-tilted reservation price.
    tilt = (inventory_ratio - params.inventory_target_pct) * GAMMA * max_spread
    r = mid - tilt

    bid = r - half_spread
    ask = r + half_spread

    # Clamp to tradeable bounds.
    bid = max(PRICE_FLOOR, min(PRICE_CEIL, bid))
    ask = max(PRICE_FLOOR, min(PRICE_CEIL, ask))

    # Enforce a minimum fillable spread, widening symmetrically about the
    # current midpoint and re-clamping. If both legs are pinned at the same
    # bound this still leaves bid == ask, which the simulator flags as
    # degenerate rather than silently emitting a crossed/zero quote.
    if ask - bid < MIN_SPREAD:
        center = (bid + ask) / 2.0
        center = max(PRICE_FLOOR + MIN_SPREAD / 2.0, min(PRICE_CEIL - MIN_SPREAD / 2.0, center))
        bid = max(PRICE_FLOOR, center - MIN_SPREAD / 2.0)
        ask = min(PRICE_CEIL, center + MIN_SPREAD / 2.0)

    size = float(params.max_position_per_market_usd)

    # Confidence: tighter quoted spread relative to max_spread => more
    # conviction. Falls in (0, 1]. When max_spread is non-positive there is no
    # reference width, so default to a neutral mid-confidence.
    quoted_spread = ask - bid
    if max_spread > 0:
        confidence = 1.0 - min(1.0, quoted_spread / max_spread)
        # Keep strictly positive so a fully-pinned quote still reports some
        # (low) confidence rather than zero.
        confidence = max(0.05, min(1.0, confidence))
    else:
        confidence = 0.5

    return {
        "bid": round(bid, 4),
        "ask": round(ask, 4),
        "size": round(size, 2),
        "confidence": round(confidence, 4),
    }


def polymarket_score(v: float, s: float, b: float = 1.0) -> float:
    """Polymarket-style maker reward score: ((v - s) / v) ** 2 * b.

    `v` is the reference (e.g. quote midpoint distance budget) and `s` the
    realised spread/distance; the closer `s` is to zero the higher the score.
    Guards against v <= 0 (returns 0.0).
    """
    if v <= 0:
        return 0.0
    return ((v - s) / v) ** 2 * b


def per_market_breaker_tripped(
    market_loss_usd: float,
    daily_loss_limit_usd: float,
    pct: float = MAX_LOSS_PER_MARKET_PCT,
) -> bool:
    """True when a single market's loss has exceeded pct of the daily limit.

    Trips strictly above pct * daily_loss_limit_usd (default 20%): at the 20%
    boundary a market is still quoting; only once it exceeds that slice does the
    breaker fire. So with a $20 daily limit, a $4 market loss (== 20%) does NOT
    trip, but a $5 loss does. A single losing market cannot consume more than its
    slice of the day's budget before NOMOS stops quoting it.
    """
    return market_loss_usd > pct * daily_loss_limit_usd


def daily_loss_breached(day_loss_usd: float, daily_loss_limit_usd: float) -> bool:
    """True when the cumulative day loss has reached the daily limit."""
    return day_loss_usd >= daily_loss_limit_usd


def market_allowed(market_tags: list[str], whitelist: list[str]) -> bool:
    """True when the market shares at least one tag with the whitelist.

    An empty whitelist allows nothing (fail-closed); a market with no tags is
    likewise not allowed.
    """
    if not whitelist or not market_tags:
        return False
    allowed = {t.lower() for t in whitelist}
    return any(str(t).lower() in allowed for t in market_tags)

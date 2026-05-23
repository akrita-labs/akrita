"""
SPATHA — Proxy-hedge instrument selection.

Import-safe (pure data + pure functions). A Polymarket position is rarely
hedgeable with the *same* asset on a perp venue, so SPATHA hedges with a
*correlated* perp. This module answers: given a market and the user's
underlying whitelist, which perp do we hedge with, and is it a direct hedge or
a correlated proxy?

Selection precedence:
  1. DIRECT  — the market maps to a perp underlying that the user whitelisted.
  2. PROXY   — otherwise, the highest-correlation whitelisted underlying whose
               correlation clears PROXY_CORR_MIN.
  3. NONE    — nothing whitelisted clears the bar; refuse to hedge.

The correlation table is a static, hand-tuned stand-in. In production this is a
rolling empirical estimate; here it is deliberately small and legible so the
decision is auditable.
"""
from __future__ import annotations

from shared.params import PROXY_CORR_MIN


# Per-market correlation of the PM exposure against each candidate perp
# underlying. Keys are the *market underlying* tag (a coarse label for what the
# market is economically exposed to), values map perp coin -> correlation.
CORRELATIONS: dict[str, dict[str, float]] = {
    "BTC": {"BTC": 1.0, "ETH": 0.85, "SOL": 0.75},
    "ETH": {"ETH": 1.0, "BTC": 0.85, "SOL": 0.78},
    "SOL": {"SOL": 1.0, "ETH": 0.78, "BTC": 0.72},
    # Rates / macro markets: no direct perp, but crypto beta to risk-on/off.
    "RATES": {"BTC": 0.72, "ETH": 0.70, "SOL": 0.60},
    "CPI": {"BTC": 0.71, "ETH": 0.68, "SOL": 0.58},
    # A market with no usable crypto correlation -> NONE.
    "WEATHER": {"BTC": 0.10, "ETH": 0.08, "SOL": 0.05},
}


# Underlyings that have a tradeable direct perp on the hedge venue.
DIRECT_PERP: set[str] = {"BTC", "ETH", "SOL"}


def select_hedge_instrument(
    market_id: str,
    whitelist: list[str],
    direct_map: dict[str, str],
) -> tuple[str | None, str]:
    """Pick the hedge instrument for ``market_id``.

    Returns ``(instrument, mode)`` where ``mode`` is one of
    ``"direct"``, ``"proxy"``, ``"none"``.

    - DIRECT: ``direct_map[market_id]`` names a perp whose underlying is in the
      whitelist -> hedge it 1:1.
    - PROXY: otherwise, look up the market's correlation row (keyed by the
      market's underlying tag) and pick the highest-correlation whitelisted
      underlying whose correlation >= PROXY_CORR_MIN.
    - NONE: nothing qualifies.
    """
    whitelisted = {u.upper() for u in whitelist}

    # 1. Direct hedge — the market has a known perp and the user allows it.
    direct = direct_map.get(market_id)
    if direct is not None:
        underlying = _underlying_of(direct)
        if underlying in whitelisted:
            return direct, "direct"

    # 2. Proxy hedge — best correlated whitelisted underlying above the floor.
    row = CORRELATIONS.get(_market_underlying(market_id, direct_map))
    if row:
        best_coin: str | None = None
        best_corr = PROXY_CORR_MIN
        for coin, corr in row.items():
            if coin in whitelisted and corr >= best_corr:
                # Strictly improve; ties keep the first (insertion) winner.
                if best_coin is None or corr > best_corr:
                    best_coin, best_corr = coin, corr
        if best_coin is not None:
            return f"{best_coin}-PERP", "proxy"

    # 3. Nothing qualifies.
    return None, "none"


def _underlying_of(instrument: str) -> str:
    """'BTC-PERP' -> 'BTC'; tolerant of case and whitespace."""
    return instrument.strip().upper().split("-")[0]


def _market_underlying(market_id: str, direct_map: dict[str, str]) -> str:
    """Resolve the coarse correlation-table key for a market.

    If the market has a direct perp mapping we key off that perp's underlying;
    otherwise fall back to interpreting the market_id itself as a tag (so macro
    markets like ``"RATES"`` / ``"CPI"`` resolve to their correlation row).
    """
    direct = direct_map.get(market_id)
    if direct is not None:
        return _underlying_of(direct)
    return market_id.strip().upper()

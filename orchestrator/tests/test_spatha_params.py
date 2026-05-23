"""Tests for the SPATHA depuration: params surface + pure hedge/proxy math.

Pure (no network). Covers:
  - SpathaParams defaults, bounds, and the depuration contract (removed knobs
    are *rejected*, not silently ignored).
  - max_funding_bps_hr coupling.
  - no_transaction_band positivity + monotonicity in risk-aversion.
  - should_hedge / funding_ceiling_ok / clamp_leverage.
  - select_hedge_instrument direct / proxy / none precedence.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.params import (
    SpathaParams,
    max_funding_bps_hr,
    validate_params,
)
from agents.spatha.hedge import (
    clamp_leverage,
    funding_ceiling_ok,
    hedge_side_for,
    kill_switch_funding_tripped,
    no_transaction_band,
    should_hedge,
)
from agents.spatha.proxy import select_hedge_instrument


# ---------------------------------------------------------------------------
# SpathaParams — defaults, bounds, and the depuration contract
# ---------------------------------------------------------------------------

def test_spatha_defaults():
    p = SpathaParams()
    assert p.hedge_band_risk_aversion == 1.0
    assert p.hedge_underlying_whitelist == ["BTC", "ETH", "SOL"]
    assert p.leverage_cap == 3
    assert p.kill_switch_funding_apr_pct == 200


def test_spatha_empty_dict_is_defaults():
    assert validate_params("spatha", {}) == SpathaParams()
    assert validate_params("spatha", None) == SpathaParams()


def test_spatha_bounds_reject_out_of_range():
    # risk-aversion floor is 0.1
    with pytest.raises(ValidationError):
        validate_params("spatha", {"hedge_band_risk_aversion": 0.05})
    # leverage cap ceiling is 10
    with pytest.raises(ValidationError):
        validate_params("spatha", {"leverage_cap": 20})


def test_spatha_bounds_accept_edges():
    assert validate_params("spatha", {"hedge_band_risk_aversion": 0.1}).hedge_band_risk_aversion == 0.1
    assert validate_params("spatha", {"hedge_band_risk_aversion": 10}).hedge_band_risk_aversion == 10
    assert validate_params("spatha", {"leverage_cap": 1}).leverage_cap == 1
    assert validate_params("spatha", {"leverage_cap": 10}).leverage_cap == 10
    assert validate_params("spatha", {"kill_switch_funding_apr_pct": 50}).kill_switch_funding_apr_pct == 50
    assert validate_params("spatha", {"kill_switch_funding_apr_pct": 500}).kill_switch_funding_apr_pct == 500


@pytest.mark.parametrize(
    "removed",
    [
        {"funding_rate_max_bps_per_hour": 5},
        {"builder_fee_rate_bps": 2},
        {"slippage_tolerance_bps": 10},
    ],
)
def test_spatha_rejects_removed_params(removed):
    """Depuration: removed knobs raise (extra='forbid'), never silently ignored."""
    with pytest.raises(ValidationError):
        validate_params("spatha", removed)


# ---------------------------------------------------------------------------
# max_funding_bps_hr — SPATHA <-> shared coupling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "a,expected",
    [(1, 30), (2, 60), (3, 90), (4, 100), (0.3, 9)],
)
def test_max_funding_bps_hr_mapping(a, expected):
    assert max_funding_bps_hr(a) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# no_transaction_band — positivity + monotonicity
# ---------------------------------------------------------------------------

def test_no_transaction_band_positive():
    w = no_transaction_band(a=1.0, cost_rate=0.006, gamma=0.1, price=1000.0)
    assert w > 0.0


def test_no_transaction_band_monotonic_in_risk_aversion():
    """Smaller risk-aversion -> wider band (more tolerant of drift)."""
    wide = no_transaction_band(a=0.5, cost_rate=0.006, gamma=0.1, price=1000.0)
    narrow = no_transaction_band(a=5.0, cost_rate=0.006, gamma=0.1, price=1000.0)
    assert wide > narrow


def test_no_transaction_band_guards_nonpositive():
    assert no_transaction_band(a=0.0, cost_rate=0.006, gamma=0.1, price=1000.0) == 0.0
    assert no_transaction_band(a=1.0, cost_rate=0.0, gamma=0.1, price=1000.0) == 0.0
    assert no_transaction_band(a=1.0, cost_rate=0.006, gamma=0.0, price=1000.0) == 0.0
    assert no_transaction_band(a=1.0, cost_rate=0.006, gamma=0.1, price=0.0) == 0.0


# ---------------------------------------------------------------------------
# should_hedge / funding_ceiling_ok / kill_switch / side / clamp
# ---------------------------------------------------------------------------

def test_should_hedge():
    assert should_hedge(net_exposure=150.0, band_usd=100.0) is True
    assert should_hedge(net_exposure=-150.0, band_usd=100.0) is True
    assert should_hedge(net_exposure=50.0, band_usd=100.0) is False
    # on the band edge -> not yet hedging (strict >)
    assert should_hedge(net_exposure=100.0, band_usd=100.0) is False


def test_funding_ceiling_ok():
    # ceiling at a=2.0 is min(30*2,100)=60
    assert funding_ceiling_ok(60.0, 2.0) is True
    assert funding_ceiling_ok(95.0, 2.0) is False


def test_kill_switch_funding_tripped():
    assert kill_switch_funding_tripped(250.0, 200.0) is True
    assert kill_switch_funding_tripped(150.0, 200.0) is False
    assert kill_switch_funding_tripped(200.0, 200.0) is False  # at threshold, not tripped


def test_hedge_side_for():
    assert hedge_side_for(100.0) == "short"
    assert hedge_side_for(-100.0) == "long"
    assert hedge_side_for(0.0) == "long"


def test_clamp_leverage():
    assert clamp_leverage(2.0, 3.0) == 2.0          # within cap
    assert clamp_leverage(8.0, 3.0) == 3.0          # clamped to cap
    assert clamp_leverage(0.5, 3.0) == 1.0          # clamped to floor of 1.0
    assert clamp_leverage(3.0, 3.0) == 3.0          # at cap


# ---------------------------------------------------------------------------
# select_hedge_instrument — direct / proxy / none precedence
# ---------------------------------------------------------------------------

def test_select_direct_when_available_and_whitelisted():
    direct_map = {"0xbbbb": "BTC-PERP"}
    instrument, mode = select_hedge_instrument(
        "0xbbbb", whitelist=["BTC", "ETH"], direct_map=direct_map
    )
    assert (instrument, mode) == ("BTC-PERP", "direct")


def test_select_falls_back_to_proxy_when_direct_not_whitelisted():
    """Direct perp exists but its underlying isn't whitelisted -> correlated proxy."""
    direct_map = {"0xbbbb": "BTC-PERP"}
    instrument, mode = select_hedge_instrument(
        "0xbbbb", whitelist=["ETH"], direct_map=direct_map
    )
    # BTC market correlates with ETH at 0.85 (>= PROXY_CORR_MIN)
    assert (instrument, mode) == ("ETH-PERP", "proxy")


def test_select_proxy_for_macro_market():
    """A macro market with no direct perp picks its best correlated whitelisted perp."""
    instrument, mode = select_hedge_instrument(
        "RATES", whitelist=["BTC", "ETH", "SOL"], direct_map={}
    )
    # RATES correlates highest with BTC (0.72) >= PROXY_CORR_MIN
    assert (instrument, mode) == ("BTC-PERP", "proxy")


def test_select_none_when_nothing_clears_corr_floor():
    instrument, mode = select_hedge_instrument(
        "WEATHER", whitelist=["BTC", "ETH", "SOL"], direct_map={}
    )
    assert (instrument, mode) == (None, "none")


def test_select_none_when_whitelist_empty():
    direct_map = {"0xbbbb": "BTC-PERP"}
    instrument, mode = select_hedge_instrument(
        "0xbbbb", whitelist=[], direct_map=direct_map
    )
    assert (instrument, mode) == (None, "none")

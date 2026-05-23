"""Tests for the depurated NOMOS parameter surface and pure breaker/score math.

Covers:
  - NomosParams defaults match the v1 spec.
  - Out-of-bounds values are rejected (offset too small, position too large).
  - REMOVED knobs (gamma, kelly_fraction, inventory_skew_eta, quote_jitter_ms)
    are rejected by extra="forbid" — depuration is enforced, not silent.
  - polymarket_score behaviour.
  - per_market_breaker_tripped threshold (20% of daily limit).
  - market_allowed whitelist semantics.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.nomos.pricing import (
    market_allowed,
    per_market_breaker_tripped,
    polymarket_score,
)
from shared.params import NomosParams, validate_params


# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------

def test_nomos_defaults():
    p = NomosParams()
    assert p.quote_spread_bps_offset_to_max_spread == 0.50
    assert p.inventory_target_pct == 0.50
    assert p.max_position_per_market_usd == 50
    assert p.daily_loss_limit_usd == 20
    assert p.market_whitelist_tags == ["crypto", "sports"]


def test_validate_params_empty_is_defaults():
    p = validate_params("nomos", {})
    assert isinstance(p, NomosParams)
    assert p.quote_spread_bps_offset_to_max_spread == 0.50


# --------------------------------------------------------------------------
# Bounds rejection
# --------------------------------------------------------------------------

def test_offset_below_min_rejected():
    with pytest.raises(ValidationError):
        NomosParams(quote_spread_bps_offset_to_max_spread=0.05)


def test_max_position_above_max_rejected():
    with pytest.raises(ValidationError):
        NomosParams(max_position_per_market_usd=2000)


# --------------------------------------------------------------------------
# Removed knobs are rejected (extra="forbid") — depuration is enforced
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs",
    [
        {"gamma": 0.1},
        {"kelly_fraction": 0.5},
        {"inventory_skew_eta": 1},
        {"quote_jitter_ms": 5},
    ],
)
def test_removed_params_rejected(kwargs):
    with pytest.raises(ValidationError):
        NomosParams(**kwargs)


def test_removed_param_rejected_via_validate_params():
    with pytest.raises(ValidationError):
        validate_params("nomos", {"gamma": 0.1})


# --------------------------------------------------------------------------
# polymarket_score
# --------------------------------------------------------------------------

def test_polymarket_score_basic():
    assert polymarket_score(100, 50) == pytest.approx(0.25)


def test_polymarket_score_increases_as_spread_tightens():
    # Smaller s (tighter) => higher score.
    assert polymarket_score(100, 25) > polymarket_score(100, 50)
    assert polymarket_score(100, 10) > polymarket_score(100, 25)


def test_polymarket_score_guards_nonpositive_v():
    assert polymarket_score(0, 50) == 0.0
    assert polymarket_score(-5, 1) == 0.0


# --------------------------------------------------------------------------
# per_market_breaker_tripped — trips at 20% of the daily limit
# --------------------------------------------------------------------------

def test_breaker_at_boundary_does_not_trip():
    # 4 == 20% of 20: at the boundary the market is still quoting.
    assert per_market_breaker_tripped(4, 20) is False


def test_breaker_above_boundary_trips():
    # 5 > 20% of 20 (=4): the breaker fires.
    assert per_market_breaker_tripped(5, 20) is True


def test_breaker_just_under_boundary():
    assert per_market_breaker_tripped(3.99, 20) is False


# --------------------------------------------------------------------------
# market_allowed
# --------------------------------------------------------------------------

def test_market_allowed_overlap():
    assert market_allowed(["crypto"], ["crypto", "sports"]) is True


def test_market_allowed_no_overlap():
    assert market_allowed(["politics"], ["crypto", "sports"]) is False


def test_market_allowed_case_insensitive():
    assert market_allowed(["Crypto"], ["crypto"]) is True


def test_market_allowed_empty_whitelist_fail_closed():
    assert market_allowed(["crypto"], []) is False


def test_market_allowed_no_tags():
    assert market_allowed([], ["crypto", "sports"]) is False

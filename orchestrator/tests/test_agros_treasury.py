"""Tests for the depurated AGROS treasury logic and parameter surface.

Covers the pure decision module (``agents.agros.treasury``):
  - target_buffer = max(redemption_buffer_usd, projected_outflow * fraction).
  - decide_action: subscribe when surplus >= min (capped at MAX_TREASURY_ACTION_USDC),
    redeem when deficit, noop inside the dead-band.
  - tier_allows_susde: only Tier C WITH explicit cooldown acceptance.
  - humanize: non-empty narrative carrying the dollar amount and "APY".
And the AgrosParams depuration:
  - REMOVED knobs (aave_chain_preference, aave_rate_floor_apy_pct) are rejected
    by extra="forbid" — depuration is enforced, not silent.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.agros import treasury
from shared.params import MAX_TREASURY_ACTION_USDC, AgrosParams


# --------------------------------------------------------------------------
# target_buffer
# --------------------------------------------------------------------------

def test_target_buffer_floored_by_redemption_buffer():
    # outflow * fraction below the floor -> floor wins.
    p = AgrosParams(redemption_buffer_usd=200, safety_buffer_fraction=1.5)
    assert treasury.target_buffer(50.0, p) == 200.0


def test_target_buffer_scaled_outflow_wins():
    # outflow * fraction above the floor -> scaled outflow wins.
    p = AgrosParams(redemption_buffer_usd=100, safety_buffer_fraction=2.0)
    assert treasury.target_buffer(300.0, p) == 600.0


# --------------------------------------------------------------------------
# decide_action
# --------------------------------------------------------------------------

def test_decide_action_subscribes_surplus_capped():
    # Big surplus -> subscribe, but capped at MAX_TREASURY_ACTION_USDC.
    p = AgrosParams(redemption_buffer_usd=200, safety_buffer_fraction=1.0)
    action, amount = treasury.decide_action(
        current_usdc=10_000.0, projected_outflow=200.0, params=p, min_subscribe=50.0
    )
    assert action == "usyc_subscribe"
    assert amount == MAX_TREASURY_ACTION_USDC


def test_decide_action_subscribe_below_cap_uses_surplus():
    # Surplus between min_subscribe and the cap -> subscribe exactly the surplus.
    p = AgrosParams(redemption_buffer_usd=200, safety_buffer_fraction=1.0)
    # target buffer = 200; current 205 -> surplus 5 (below min 4 here)
    action, amount = treasury.decide_action(
        current_usdc=206.0, projected_outflow=200.0, params=p, min_subscribe=4.0
    )
    assert action == "usyc_subscribe"
    assert amount == pytest.approx(6.0)
    assert amount <= MAX_TREASURY_ACTION_USDC


def test_decide_action_redeems_on_deficit_capped():
    # Deep deficit -> redeem, capped at MAX_TREASURY_ACTION_USDC.
    p = AgrosParams(redemption_buffer_usd=200, safety_buffer_fraction=1.0)
    action, amount = treasury.decide_action(
        current_usdc=0.0, projected_outflow=200.0, params=p, min_subscribe=50.0
    )
    assert action == "usyc_redeem"
    assert amount == MAX_TREASURY_ACTION_USDC


def test_decide_action_noop_in_deadband():
    # Surplus magnitude below min_subscribe in either direction -> noop.
    p = AgrosParams(redemption_buffer_usd=200, safety_buffer_fraction=1.0)
    action, amount = treasury.decide_action(
        current_usdc=210.0, projected_outflow=200.0, params=p, min_subscribe=50.0
    )
    assert action == "noop"
    assert amount == 0.0


# --------------------------------------------------------------------------
# tier_allows_susde
# --------------------------------------------------------------------------

def test_tier_allows_susde_c_without_acceptance_false():
    assert treasury.tier_allows_susde(
        AgrosParams(tier="C", susde_cooldown_acceptance=False)
    ) is False


def test_tier_allows_susde_c_with_acceptance_true():
    assert treasury.tier_allows_susde(
        AgrosParams(tier="C", susde_cooldown_acceptance=True)
    ) is True


@pytest.mark.parametrize("tier", ["A", "B"])
def test_tier_allows_susde_non_c_always_false(tier):
    # Even with acceptance flagged, only Tier C may allocate to sUSDe.
    assert treasury.tier_allows_susde(
        AgrosParams(tier=tier, susde_cooldown_acceptance=True)
    ) is False


# --------------------------------------------------------------------------
# humanize
# --------------------------------------------------------------------------

@pytest.mark.parametrize("action", ["usyc_subscribe", "usyc_redeem", "noop"])
def test_humanize_non_empty_and_mentions_apy(action):
    text = treasury.humanize(
        action=action,
        amount=7.50,
        projected_outflow=200.0,
        buffer=300.0,
        apy=4.87,
        tier="B",
    )
    assert isinstance(text, str)
    assert text.strip()
    assert "APY" in text


def test_humanize_subscribe_contains_dollar_amount():
    text = treasury.humanize(
        action="usyc_subscribe",
        amount=7.50,
        projected_outflow=200.0,
        buffer=300.0,
        apy=4.87,
        tier="B",
    )
    assert "$7.50" in text
    assert "4.87% APY" in text


# --------------------------------------------------------------------------
# AgrosParams depuration — removed knobs are rejected, not ignored.
# --------------------------------------------------------------------------

def test_agros_params_rejects_aave_chain_preference():
    with pytest.raises(ValidationError):
        AgrosParams(aave_chain_preference="polygon")


def test_agros_params_rejects_aave_rate_floor():
    with pytest.raises(ValidationError):
        AgrosParams(aave_rate_floor_apy_pct=3)

"""Pure unit tests for the Rugpull Oracle backend helpers (Phase 3 tail)."""
from agents.agros.bond_treasury import bond_funding_plan, idle_to_usyc
from agents.nomos.claim_issuer import credibility_for, source_commit_b32
from agents.spatha.claim_hedge import claim_hedge_plan


def test_source_commit_b32_pads_to_bytes32():
    b = source_commit_b32("abc123")
    assert b.startswith("0x") and len(b) == 66
    assert b.endswith("abc123")


def test_credibility_bounded():
    c = credibility_for({"token": "PEPE"})
    assert 0.0 <= c <= 1.0


def test_bond_funding_plan_shortfall_triggers_gateway():
    p = bond_funding_plan(100.0, 250.0, source_chain="base-sepolia")
    assert p["target_usdc"] == 250.0
    assert p["shortfall_usdc"] == 150.0
    assert p["action"] == "gateway_inflow"


def test_bond_funding_plan_covered_is_noop():
    p = bond_funding_plan(500.0, 250.0, source_chain="base-sepolia")
    assert p["shortfall_usdc"] == 0.0
    assert p["action"] == "none"


def test_bond_funding_plan_no_source_no_action():
    p = bond_funding_plan(0.0, 100.0, source_chain="")
    assert p["shortfall_usdc"] == 100.0
    assert p["action"] == "none"  # nowhere to pull from


def test_idle_to_usyc_parks_surplus():
    assert idle_to_usyc(300.0, 250.0) == 50.0
    assert idle_to_usyc(255.0, 250.0) == 0.0  # below min_subscribe
    assert idle_to_usyc(100.0, 250.0) == 0.0  # underfunded


def test_claim_hedge_plan_within_band_is_none():
    assert claim_hedge_plan("PEPE", 100.0, band_usd=500.0)["action"] == "none"


def test_claim_hedge_plan_opens_opposite_drift():
    p = claim_hedge_plan("PEPE", 2000.0, band_usd=500.0, leverage_cap=3.0)
    assert p["action"] == "open"
    assert p["instrument"] == "PEPE-PERP"
    assert p["side"] == "short"  # net long exposure -> short hedge
    assert 1.0 <= p["leverage"] <= 3.0

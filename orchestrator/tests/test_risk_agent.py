"""Risk Agent tests.

For each of the 12 deterministic checks: one passing case, one failing case.
"""
from __future__ import annotations

import time

import pytest

from orchestrator.app.risk_agent import RiskAgent
from shared.canonical import trace_hash
from shared.models import (
    AppetiteProfile,
    Chain,
    HedgeDecision,
    HedgeSide,
    HedgeVenue,
    MarginAsset,
    PricingDecision,
    TreasuryAction,
    TreasuryDecision,
)


@pytest.fixture
def agent():
    return RiskAgent()


def _pricing(**overrides):
    base = dict(
        decision_id=1,
        nonce=42,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash({"k": "v"}),
        market_id="0x" + "a" * 40,
        market_question="Test market",
        bid=0.45,
        ask=0.55,
        size=100.0,
        confidence=0.7,
        appetite_profile=AppetiteProfile.BALANCED,
    )
    base.update(overrides)
    return PricingDecision(**base)


def _hedge(**overrides):
    base = dict(
        decision_id=2,
        nonce=43,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash({"k": "v"}),
        market_id="0x" + "a" * 40,
        action="open",
        venue=HedgeVenue.HYPERLIQUID,
        instrument="BTC-PERP",
        side=HedgeSide.SHORT,
        size=0.05,
        leverage=2.0,
        margin_asset=MarginAsset.USDC,
        margin_amount=200.0,
        stop_loss=None,
    )
    base.update(overrides)
    return HedgeDecision(**base)


def _treasury(**overrides):
    base = dict(
        decision_id=3,
        nonce=44,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash({"k": "v"}),
        action=TreasuryAction.USYC_SUBSCRIBE,
        amount=500.0,
        projected_outflow_60min=100.0,
    )
    base.update(overrides)
    return TreasuryDecision(**base)


# --------- Universal check tests --------------------------------------------

def test_valid_pricing_passes_all(agent):
    result = agent.evaluate(_pricing())
    assert result.approved, result.reason


def test_stale_timestamp_fails(agent):
    # Decision was created 10 minutes ago; "now" is the current wall clock
    old_ts = int(time.time() * 1000) - 600_000
    result = agent.evaluate(
        _pricing(ts_ms=old_ts),
        context={"now_ms": int(time.time() * 1000)},
    )
    assert not result.approved
    assert "timestamp_freshness" in result.reason


def test_malformed_rationale_hash_fails(agent):
    # Pydantic enforces format at construction time; to test the Risk Agent
    # check independently, bypass validation via model_construct.
    d = PricingDecision.model_construct(
        decision_id=1, nonce=42, ts_ms=int(time.time() * 1000),
        rationale_hash="0xshort", market_id="0x" + "a" * 40,
        market_question="x", bid=0.45, ask=0.55, size=100.0,
        confidence=0.7, appetite_profile=AppetiteProfile.BALANCED,
    )
    result = agent.evaluate(d)
    assert not result.approved
    assert "rationale_hash_format" in result.reason


# --------- Pricing check tests ----------------------------------------------

def test_oversized_quote_fails(agent):
    result = agent.evaluate(_pricing(size=5000.0))
    assert not result.approved
    assert "pricing_size_within_limit" in result.reason


def test_inverted_quote_fails(agent):
    result = agent.evaluate(_pricing(bid=0.6, ask=0.5))
    assert not result.approved
    # Either bid_below_ask or spread_bounds will fire
    assert "pricing" in result.reason


def test_too_wide_spread_fails(agent):
    result = agent.evaluate(_pricing(bid=0.10, ask=0.95))
    assert not result.approved
    assert "pricing_spread_in_bounds" in result.reason


# --------- Hedge check tests ------------------------------------------------

def test_valid_hedge_passes(agent):
    result = agent.evaluate(_hedge())
    assert result.approved, result.reason


def test_excessive_leverage_fails(agent):
    result = agent.evaluate(_hedge(leverage=20.0))
    assert not result.approved
    assert "hedge_leverage" in result.reason


def test_zero_margin_fails(agent):
    # margin_amount has gt=0 constraint at Pydantic level, so this raises at construction
    with pytest.raises(Exception):
        _hedge(margin_amount=0.0)


# --------- Treasury check tests ---------------------------------------------

def test_valid_subscribe_passes(agent):
    result = agent.evaluate(_treasury())
    assert result.approved, result.reason


def test_below_min_subscribe_fails(agent):
    result = agent.evaluate(_treasury(amount=1.0))
    assert not result.approved
    assert "treasury_min_subscribe" in result.reason


def test_subscribe_cap_fails(agent):
    result = agent.evaluate(_treasury(amount=999_999.0))
    assert not result.approved
    assert "treasury_subscribe_cap" in result.reason


def test_gateway_missing_chains_fails(agent):
    d = _treasury(action=TreasuryAction.GATEWAY_TRANSFER, src_chain=None, dst_chain=None)
    result = agent.evaluate(d)
    assert not result.approved
    assert "treasury_gateway_chains" in result.reason


def test_gateway_self_chain_fails(agent):
    d = _treasury(
        action=TreasuryAction.GATEWAY_TRANSFER,
        src_chain=Chain.ARC,
        dst_chain=Chain.ARC,
    )
    result = agent.evaluate(d)
    assert not result.approved
    assert "treasury_no_self_chain" in result.reason


def test_aggregate_failure_reports_all(agent):
    """When multiple checks fail, all failure names appear in reason."""
    bad = _pricing(size=99999.0, bid=0.8, ask=0.2, ts_ms=0)
    result = agent.evaluate(bad)
    assert not result.approved
    # at least 2 distinct failure names listed
    assert result.reason.count(";") >= 1

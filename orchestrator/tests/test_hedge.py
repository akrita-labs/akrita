"""Tests for the Hyperliquid hedge adapter (PR 5).

Three tiers (mirrors test_real_adapters.py):
  - Pure: instrument->coin mapping and the unfunded write-gate (no network).
  - Network-gated reads: funding rate / account value / positions hit live HL
    testnet — these work regardless of account funding (AKRITA_LIVE_TESTS=1).
  - Network-gated write-gate: open/close refuse clearly while the master
    account is unfunded (also live, since the gate reads account value).

`asyncio_mode = auto` is configured, so async tests run without a marker.
"""
from __future__ import annotations

import os

import pytest


_LIVE = os.environ.get("AKRITA_LIVE_TESTS") == "1"


# --------------------------------------------------------------------------
# Pure — instrument <-> coin mapping (no network)
# --------------------------------------------------------------------------

def test_instrument_to_coin_strips_perp_suffix():
    from adapters.real.hyperliquid import _coin_of

    assert _coin_of("BTC-PERP") == "BTC"
    assert _coin_of("ETH-PERP") == "ETH"
    assert _coin_of("eth-perp") == "ETH"   # case-insensitive
    assert _coin_of("BTC") == "BTC"        # already a bare coin
    assert _coin_of(" SOL-PERP ") == "SOL"  # tolerant of whitespace


# --------------------------------------------------------------------------
# Network-gated — live HL reads (no margin required, public + user query API)
# --------------------------------------------------------------------------

@pytest.mark.skipif(not _LIVE, reason="set AKRITA_LIVE_TESTS=1")
async def test_funding_rate_live():
    from adapters.real.hyperliquid import HyperliquidReal

    hl = HyperliquidReal()
    rate = await hl.get_funding_rate("BTC-PERP")
    # A real (small) hourly funding rate — bounded sanity, not a fixed value.
    assert isinstance(rate, float)
    assert abs(rate) < 0.01, f"funding rate {rate} outside sane band"

    # ETH resolves too (separate coin in the universe).
    assert isinstance(await hl.get_funding_rate("ETH-PERP"), float)


@pytest.mark.skipif(not _LIVE, reason="set AKRITA_LIVE_TESTS=1")
async def test_funding_rate_unknown_instrument_raises_live():
    from adapters.real.hyperliquid import HyperliquidReal

    hl = HyperliquidReal()
    with pytest.raises(KeyError):
        await hl.get_funding_rate("NOTACOIN-PERP")


@pytest.mark.skipif(not _LIVE, reason="set AKRITA_LIVE_TESTS=1")
async def test_account_value_and_positions_live():
    from adapters.real.hyperliquid import HyperliquidReal
    from adapters.base import HedgePosition

    hl = HyperliquidReal()
    av = await hl.get_account_value()
    wd = await hl.get_withdrawable()
    assert isinstance(av, float) and av >= 0.0
    assert isinstance(wd, float) and wd >= 0.0

    positions = await hl.get_open_positions()
    assert isinstance(positions, list)
    for p in positions:
        assert isinstance(p, HedgePosition)
        assert p.venue == "hyperliquid"
        assert p.side in ("long", "short")
        assert p.size > 0.0


@pytest.mark.skipif(not _LIVE, reason="set AKRITA_LIVE_TESTS=1")
async def test_position_id_coin_roundtrip_live():
    """position_id is the HL asset index — deterministic and reversible."""
    from adapters.real.hyperliquid import HyperliquidReal

    hl = HyperliquidReal()
    btc_id = hl._id_for("BTC")
    assert hl._coin_for(btc_id) == "BTC"
    assert hl._coin_for(hl._id_for("ETH")) == "ETH"


# --------------------------------------------------------------------------
# Network-gated — the write path is gated while the account is unfunded
# --------------------------------------------------------------------------

@pytest.mark.skipif(not _LIVE, reason="set AKRITA_LIVE_TESTS=1")
async def test_open_position_gated_when_unfunded_live():
    """open_position must refuse clearly (not fire a doomed order) when the
    master account holds no margin. If the account has since been funded this
    test is skipped — we never want to assert a *failure* on a funded account.
    """
    from adapters.real.hyperliquid import HyperliquidReal

    hl = HyperliquidReal()
    if await hl.get_account_value() >= 1.0:
        pytest.skip("HL master account is funded — open-gate no longer applies")

    with pytest.raises(RuntimeError, match="unfunded"):
        await hl.open_position("BTC-PERP", "short", 0.001, 50.0, leverage=2.0)


@pytest.mark.skipif(not _LIVE, reason="set AKRITA_LIVE_TESTS=1")
async def test_close_position_gated_when_unfunded_live():
    from adapters.real.hyperliquid import HyperliquidReal

    hl = HyperliquidReal()
    if await hl.get_account_value() >= 1.0:
        pytest.skip("HL master account is funded — close-gate no longer applies")

    with pytest.raises(RuntimeError, match="unfunded"):
        await hl.close_position(hl._id_for("BTC"))

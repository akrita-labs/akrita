"""Tests for the live adapter layer (PR 2).

Three tiers:
  - Pure: stub adapters raise clearly (no creds, no network).
  - Creds-gated: the factory builds a complete container (needs Circle env).
  - Network-gated: ArcReal reads hit live Arc (only when AKRITA_LIVE_TESTS=1).
"""
from __future__ import annotations

import os

import pytest

from shared.config import settings


# --------------------------------------------------------------------------
# Pure — stub adapters
# --------------------------------------------------------------------------

async def test_stub_adapters_raise_not_implemented():
    from adapters.real.stubs import (
        GatewayNotBuilt,
        HyperliquidNotBuilt,
        PolymarketNotBuilt,
        USYCNotBuilt,
    )

    with pytest.raises(NotImplementedError, match="PR 3"):
        await PolymarketNotBuilt().get_orderbook("0xabc")
    with pytest.raises(NotImplementedError, match="PR 5"):
        await HyperliquidNotBuilt().open_position("BTC-PERP", "long", 1.0, 10.0)
    with pytest.raises(NotImplementedError, match="PR 4"):
        await GatewayNotBuilt().transfer("w", 1.0, "arc", "polygon")
    with pytest.raises(NotImplementedError, match="PR 4"):
        await USYCNotBuilt().subscribe("w", 1.0)


def test_stub_dunder_access_does_not_raise_not_implemented():
    """Private/dunder access should AttributeError, not hand back a coroutine."""
    from adapters.real.stubs import PolymarketNotBuilt

    with pytest.raises(AttributeError):
        PolymarketNotBuilt()._secret


# --------------------------------------------------------------------------
# Creds-gated — full factory container
# --------------------------------------------------------------------------

_HAS_CIRCLE = bool(settings.circle_api_key and settings.circle_api_key.count(":") == 2)


@pytest.mark.skipif(not _HAS_CIRCLE, reason="needs CIRCLE_API_KEY")
def test_factory_builds_complete_container():
    from adapters import Adapters, get_adapters, reset_for_tests

    reset_for_tests()
    a = get_adapters()
    assert isinstance(a, Adapters)
    # Every slot is populated (real or stub) — none is None.
    for field in ("polymarket", "hyperliquid", "wallets", "usyc", "gateway", "nanopayment", "arc"):
        assert getattr(a, field) is not None
    reset_for_tests()


# --------------------------------------------------------------------------
# Network-gated — live Arc reads
# --------------------------------------------------------------------------

_LIVE = os.environ.get("AKRITA_LIVE_TESTS") == "1"


@pytest.mark.skipif(not (_LIVE and _HAS_CIRCLE), reason="set AKRITA_LIVE_TESTS=1 + Circle creds")
async def test_arc_reads_live():
    from adapters.real.arc import ArcReal
    from adapters.real.circle_wallets import CircleWalletsReal

    arc = ArcReal(CircleWalletsReal())
    assert await arc.get_chain_id() == settings.arc_chain_id
    assert await arc.get_block_number() > 0


@pytest.mark.skipif(
    not (_LIVE and _HAS_CIRCLE and settings.trace_registry_addr),
    reason="set AKRITA_LIVE_TESTS=1 + deployed contracts",
)
async def test_trace_keeper_is_authorized_live():
    from adapters.real.arc import ArcReal
    from adapters.real.circle_wallets import CircleWalletsReal

    arc = ArcReal(CircleWalletsReal())
    assert await arc.is_authorized_keeper(settings.trace_wallet_addr) is True


# --------------------------------------------------------------------------
# Network-gated — live Polymarket reads (no creds needed, public CLOB)
# --------------------------------------------------------------------------

@pytest.mark.skipif(not _LIVE, reason="set AKRITA_LIVE_TESTS=1")
async def test_polymarket_orderbook_ordering_live():
    import httpx

    from adapters.real.polymarket import PolymarketReal

    pm = PolymarketReal()
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "akrita"}) as c:
        d = (await c.get("https://clob.polymarket.com/sampling-markets?limit=20")).json()
    cid = next(m["condition_id"] for m in d["data"] if m.get("accepting_orders") and m.get("tokens"))

    book = await pm.get_orderbook(cid, depth=5)
    assert book.bids and book.asks
    # index 0 must be best on each side, and bid <= ask
    assert book.bids[0].price == max(b.price for b in book.bids)
    assert book.asks[0].price == min(a.price for a in book.asks)
    assert book.best_bid <= book.best_ask
    assert await pm.get_market_question(cid)


async def test_polymarket_write_path_gated_without_signer():
    """submit_quote must refuse clearly when the signer EOA / collateral
    isn't provisioned (pure: no network, no creds beyond .env)."""
    from adapters.real.polymarket import PolymarketReal

    pm = PolymarketReal()
    with pytest.raises(RuntimeError):
        await pm.submit_quote("0x" + "ab" * 32, 0.4, 0.6, 10.0, settings.poly_builder_code or "0x")

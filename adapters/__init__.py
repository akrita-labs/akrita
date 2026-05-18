"""
Adapter factory.

This is the single seam where mock vs real adapters get chosen.
Every call site in the codebase imports through here:

    from adapters import get_adapters
    adapters = get_adapters()
    book = await adapters.polymarket.get_orderbook(market_id)

When MOCK_MODE=1 (default), returns in-memory mocks.
When MOCK_MODE=0, returns real implementations (still TODO — Day 2+).

The agents and orchestrator never know whether they're talking to
real services or mocks. That's the entire point of this pattern.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from adapters.base import (
    ArcAdapter,
    CircleWalletsAdapter,
    GatewayAdapter,
    HyperliquidAdapter,
    NanopaymentAdapter,
    PolymarketAdapter,
    USYCAdapter,
)


@dataclass
class Adapters:
    polymarket: PolymarketAdapter
    hyperliquid: HyperliquidAdapter
    wallets: CircleWalletsAdapter
    usyc: USYCAdapter
    gateway: GatewayAdapter
    nanopayment: NanopaymentAdapter
    arc: ArcAdapter


_singleton: Adapters | None = None


def get_adapters() -> Adapters:
    """Process-singleton adapter container.

    First call constructs the adapters (mock or real) and stashes them.
    All subsequent calls return the same container.
    """
    global _singleton
    if _singleton is not None:
        return _singleton

    mock_mode = os.environ.get("MOCK_MODE", "1") == "1"
    if mock_mode:
        _singleton = _build_mock_adapters()
    else:
        _singleton = _build_real_adapters()
    return _singleton


def _build_mock_adapters() -> Adapters:
    from adapters.mock.circle import (
        MockArc,
        MockCircleWallets,
        MockGateway,
        MockNanopayment,
        MockUSYC,
    )
    from adapters.mock.hyperliquid import MockHyperliquid
    from adapters.mock.polymarket import MockPolymarket

    wallets = MockCircleWallets()
    return Adapters(
        polymarket=MockPolymarket(),
        hyperliquid=MockHyperliquid(),
        wallets=wallets,
        usyc=MockUSYC(wallets),
        gateway=MockGateway(wallets),
        nanopayment=MockNanopayment(wallets),
        arc=MockArc(),
    )


def _build_real_adapters() -> Adapters:
    """Real adapter wiring.

    This is the function to fill in during the hackathon as each
    real integration comes online. Suggested order:

      Day 1-2: real Circle Wallets + real Arc RPC (testnet)
      Day 3:   real Polymarket V2 client (mainnet, builder code admitted)
      Day 4:   real USYC adapter (testnet, allowlist approved)
      Day 5:   real Gateway adapter (testnet/mainnet)
      Day 6:   real Hyperliquid testnet adapter
      Day 7+:  real Nanopayment / IPFS pin provider
    """
    raise NotImplementedError(
        "Real adapters not wired yet. Run with MOCK_MODE=1 for now."
    )


def reset_for_tests() -> None:
    """Test helper — force a fresh adapter container on the next call."""
    global _singleton
    _singleton = None

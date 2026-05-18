"""
Adapter factory.

This is the single seam where adapters get constructed. Every call
site in the codebase imports through here:

    from adapters import get_adapters
    adapters = get_adapters()
    book = await adapters.polymarket.get_orderbook(market_id)

`get_adapters()` builds the live adapter container from
`adapters.real`. The agents and orchestrator never know which
concrete client they are talking to — they only see the protocols
in `adapters.base`. That is the entire point of this pattern.
"""
from __future__ import annotations

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

    First call constructs the live adapters and stashes them.
    All subsequent calls return the same container.
    """
    global _singleton
    if _singleton is not None:
        return _singleton

    _singleton = _build_real_adapters()
    return _singleton


def _build_real_adapters() -> Adapters:
    """Live adapter wiring.

    Concrete clients live under `adapters/real/` behind the protocols
    in `adapters/base.py`. Fill this in per the live implementation
    plan (Phase 1 — real adapter layer):

      Arc, Circle Wallets/signing, Polymarket V2, Gateway, USYC,
      Nanopayment sidecar, Hyperliquid.
    """
    raise NotImplementedError(
        "Real adapters not wired yet. Implement adapters/real/ per "
        "docs/LIVE_IMPLEMENTATION_PLAN.md Phase 1 and wire them here."
    )


def reset_for_tests() -> None:
    """Test helper — force a fresh adapter container on the next call."""
    global _singleton
    _singleton = None

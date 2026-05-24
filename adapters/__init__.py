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
from typing import TYPE_CHECKING

from adapters.base import (
    ArcAdapter,
    CircleWalletsAdapter,
    GatewayAdapter,
    HyperliquidAdapter,
    NanopaymentAdapter,
    PolymarketAdapter,
    USYCAdapter,
)

if TYPE_CHECKING:
    from adapters.real.claim_registry import ClaimRegistryReal


@dataclass
class Adapters:
    polymarket: PolymarketAdapter
    hyperliquid: HyperliquidAdapter
    wallets: CircleWalletsAdapter
    usyc: USYCAdapter
    gateway: GatewayAdapter
    nanopayment: NanopaymentAdapter
    arc: ArcAdapter
    claim_registry: "ClaimRegistryReal"  # Rugpull Oracle (Pivot 1)


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
    """Live adapter wiring — all seven adapters are real implementations.

      - CircleWalletsReal — MPC signing + contract execution + balances
      - ArcReal           — Arc reads (web3) + trace commits (via Circle)
      - NanopaymentReal   — IPFS pinning via Pinata
      - PolymarketReal    — V2 CLOB reads + builder-attributed orders
      - USYCReal          — ERC-4626 Teller subscribe/redeem + NAV/APY
      - GatewayReal       — Circle Gateway cross-chain USDC
      - HyperliquidReal   — perp hedge venue (raw-key signed)

    Some write paths are gated at runtime on external prerequisites
    (Polymarket pUSD collateral, USYC Teller role grant, Gateway deposit,
    HL account funding) and raise a clear error until those are satisfied.
    """
    from adapters.real.arc import ArcReal
    from adapters.real.circle_wallets import CircleWalletsReal
    from adapters.real.gateway import GatewayReal
    from adapters.real.hyperliquid import HyperliquidReal
    from adapters.real.nanopayment import NanopaymentReal
    from adapters.real.polymarket import PolymarketReal
    from adapters.real.usyc import USYCReal
    from adapters.real.claim_registry import ClaimRegistryReal

    wallets = CircleWalletsReal()
    return Adapters(
        polymarket=PolymarketReal(),
        hyperliquid=HyperliquidReal(),
        wallets=wallets,
        usyc=USYCReal(wallets),
        gateway=GatewayReal(wallets),
        nanopayment=NanopaymentReal(),
        arc=ArcReal(wallets),
        claim_registry=ClaimRegistryReal(wallets),
    )


def reset_for_tests() -> None:
    """Test helper — force a fresh adapter container on the next call."""
    global _singleton
    _singleton = None

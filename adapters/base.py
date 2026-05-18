"""
AKRITA — Adapter protocol definitions.

Every external integration (Polymarket V2, Hyperliquid, Circle Wallets,
Circle USYC, Circle Gateway, Circle Nanopayments, Arc RPC) has a
Protocol class here. Concrete live implementations live in
adapters/real/.

The Orchestrator and agents only ever import these Protocols and call
them through `get_adapters()`, which constructs the live adapter
container. Decoupling the call sites from the concrete clients lets
each integration come online independently behind a stable interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Optional


# ---------------------------------------------------------------------------
# Dataclasses (lightweight value objects shared between adapters)
# ---------------------------------------------------------------------------

@dataclass
class OrderbookLevel:
    price: float
    size: float


@dataclass
class Orderbook:
    market_id: str
    bids: list[OrderbookLevel]
    asks: list[OrderbookLevel]
    ts_ms: int

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 1.0

    @property
    def spread_bps(self) -> int:
        if not self.bids or not self.asks:
            return 10000
        return int((self.best_ask - self.best_bid) * 10000)

    @property
    def microprice(self) -> float:
        if not self.bids or not self.asks:
            return 0.5
        b, a = self.best_bid, self.best_ask
        bs = self.bids[0].size
        ass_ = self.asks[0].size
        if bs + ass_ == 0:
            return (a + b) / 2
        return (a * bs + b * ass_) / (bs + ass_)


@dataclass
class Fill:
    market_id: str
    price: float
    size: float
    side: str
    builder_fee_usdc: float
    ts_ms: int
    tx_hash: str


@dataclass
class HedgePosition:
    position_id: int
    venue: str
    instrument: str
    side: str
    size: float
    entry_price: float
    margin_asset: str
    margin_amount: float
    status: str  # open / closed / liquidated
    pnl_usdc: float = 0.0


@dataclass
class TxReceipt:
    tx_hash: str
    block_number: int
    gas_paid_usdc: float
    status: str  # success / failed


@dataclass
class TransferReceipt:
    amount_usdc: float
    src_chain: str
    dst_chain: str
    src_tx: str
    dst_tx: str
    elapsed_ms: int


@dataclass
class SubscribeReceipt:
    usdc_in: float
    usyc_out: float
    nav: float
    tx_hash: str


@dataclass
class RedeemReceipt:
    usyc_in: float
    usdc_out: float
    fee: float
    tx_hash: str


# ---------------------------------------------------------------------------
# Polymarket V2 adapter protocol
# ---------------------------------------------------------------------------

class PolymarketAdapter(Protocol):
    """Polymarket V2 CLOB integration.

    Notes for real implementation (hackathon Day 2-3):
    - Use py-clob-client-v2, NOT the legacy py-clob-client
    - EIP-712 domain version is "2" (V2 cutover April 28, 2026)
    - Collateral is pUSD, NOT USDC.e — wrap USDC at the Collateral Onramp
    - Order struct: timestamp(ms), metadata(bytes32), builder(bytes32)
      replaced nonce, feeRateBps, taker
    - Builder code is set per-order in the signed struct
    """

    async def get_orderbook(self, market_id: str, depth: int = 10) -> Orderbook:
        ...

    async def get_recent_fills(self, market_id: str, n: int = 50) -> list[Fill]:
        ...

    async def submit_quote(
        self,
        market_id: str,
        bid: float,
        ask: float,
        size: float,
        builder_code: str,
    ) -> tuple[str, str]:
        """Returns (bid_order_id, ask_order_id)."""
        ...

    async def cancel_order(self, order_id: str) -> bool:
        ...

    async def get_attributed_fills_since(self, since_ts_ms: int) -> list[Fill]:
        ...

    async def get_market_question(self, market_id: str) -> str:
        ...


# ---------------------------------------------------------------------------
# Hyperliquid (hedge) adapter protocol
# ---------------------------------------------------------------------------

class HyperliquidAdapter(Protocol):
    """Hyperliquid testnet perp venue for hedge legs.

    Real implementation notes:
    - HL has its own L1; not EVM-compatible
    - Use hyperliquid-python-sdk
    - Margin: USDC (not USYC; USYC would be Arc-native perp)
    - Need to bridge USDC to HL via the HL bridge or Gateway when supported
    """

    async def open_position(
        self,
        instrument: str,
        side: str,
        size: float,
        margin_amount: float,
        leverage: float = 1.0,
        stop_loss: Optional[float] = None,
    ) -> HedgePosition:
        ...

    async def close_position(self, position_id: int) -> HedgePosition:
        ...

    async def get_position(self, position_id: int) -> HedgePosition:
        ...

    async def get_open_positions(self) -> list[HedgePosition]:
        ...

    async def get_funding_rate(self, instrument: str) -> float:
        ...


# ---------------------------------------------------------------------------
# Circle Wallets adapter protocol
# ---------------------------------------------------------------------------

class CircleWalletsAdapter(Protocol):
    """Circle Developer-Controlled Wallets.

    Real implementation: developers.circle.com/wallets
    - MPC-secured private keys
    - Spend policies enforced at signing layer
    - Each agent gets its own scoped wallet
    """

    async def sign_user_op(self, wallet_id: str, user_op: dict) -> dict:
        ...

    async def sign_eip712(self, wallet_id: str, typed_data: dict) -> str:
        ...

    async def get_balance(self, wallet_id: str, chain: str) -> dict:
        """Returns {'USDC': float, 'USYC': float, 'pUSD': float}."""
        ...


# ---------------------------------------------------------------------------
# Circle USYC adapter protocol
# ---------------------------------------------------------------------------

class USYCAdapter(Protocol):
    """Circle USYC tokenized money market fund.

    During the hackathon: USE TESTNET USYC ON ARC.
    Mainnet USYC has $100K minimum and is institutional-only.
    Testnet flow per docs.arc.io:
      1. Get testnet USDC from Circle Faucet
      2. Open support ticket requesting allowlisting + Arc testnet wallet
      3. Wait 24-48h for approval
      4. Call USYC Teller contract on Arc testnet

    FILE THE ALLOWLIST TICKET ON DAY 1 OF THE HACKATHON.
    """

    async def subscribe(self, wallet_id: str, amount_usdc: float) -> SubscribeReceipt:
        ...

    async def redeem(self, wallet_id: str, amount_usyc: float) -> RedeemReceipt:
        ...

    async def get_balance(self, wallet_id: str) -> float:
        ...

    async def get_current_yield_apy(self) -> float:
        ...

    async def get_nav_per_share(self) -> float:
        ...


# ---------------------------------------------------------------------------
# Circle Gateway adapter protocol
# ---------------------------------------------------------------------------

class GatewayAdapter(Protocol):
    """Circle Gateway — cross-chain USDC in <500ms.

    Real implementation: developers.circle.com/gateway
    Supported chains as of May 2026: Arbitrum, Avalanche, Base, Ethereum,
    Optimism, Polygon, Unichain + others. Arc support in development.

    Fee: 0.5 bps on-chain during early access (through June 30, 2026)
    """

    async def transfer(
        self,
        wallet_id: str,
        amount_usdc: float,
        src_chain: str,
        dst_chain: str,
    ) -> TransferReceipt:
        ...

    async def get_unified_balance(self, wallet_id: str) -> float:
        ...


# ---------------------------------------------------------------------------
# Circle Nanopayments adapter protocol
# ---------------------------------------------------------------------------

class NanopaymentAdapter(Protocol):
    """Circle Nanopayments — gas-free USDC at $0.000001 granularity.

    Used to pay IPFS pin providers per-trace. Batched settlement keeps
    per-decision cost below the value of the trace.
    """

    async def pay(self, recipient: str, amount_usdc: float, memo: str = "") -> str:
        """Returns settlement reference."""
        ...

    async def pin_to_ipfs(self, content_bytes: bytes, max_price_usdc: float = 0.005) -> str:
        """Pins content; returns IPFS CID. Pays via Nanopayment."""
        ...

    async def fetch_from_ipfs(self, cid: str) -> bytes | None:
        """Fetch previously pinned content by CID. Returns None if unavailable."""
        ...


# ---------------------------------------------------------------------------
# Arc RPC adapter protocol
# ---------------------------------------------------------------------------

class ArcAdapter(Protocol):
    """Arc L1 read/write surface (testnet during hackathon).

    Arc is EVM-compatible. USDC is native gas. Sub-second finality.
    Mainnet not yet live as of May 2026 — use testnet RPC.
    """

    async def call_contract(
        self,
        contract_addr: str,
        function: str,
        args: list,
    ) -> bytes:
        ...

    async def submit_tx(
        self,
        wallet_id: str,
        contract_addr: str,
        calldata: bytes,
    ) -> TxReceipt:
        ...

    async def get_block_number(self) -> int:
        ...

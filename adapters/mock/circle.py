"""
Mock Circle + Arc adapters.

All in-memory; reset on restart. The interfaces match real Circle
SDK shapes (verified against developers.circle.com docs May 2026).

Critical real-implementation notes are inlined as TODO comments at
each point where the real SDK call goes.
"""
from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict
from typing import Optional

from adapters.base import (
    ArcAdapter,
    CircleWalletsAdapter,
    GatewayAdapter,
    NanopaymentAdapter,
    RedeemReceipt,
    SubscribeReceipt,
    TransferReceipt,
    TxReceipt,
    USYCAdapter,
)


# ---------------------------------------------------------------------------
# Mock Circle Wallets
# ---------------------------------------------------------------------------

class MockCircleWallets(CircleWalletsAdapter):
    """In-memory wallet store. Each agent gets its own wallet ID at boot."""

    def __init__(self, initial_balances: Optional[dict] = None):
        # wallet_id -> chain -> token -> amount
        self._balances: dict[str, dict[str, dict[str, float]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(float))
        )
        # Seed default wallets with starting USDC
        seed = initial_balances or {
            "nomos-keeper": {"arc": {"USDC": 5000.0}, "polygon": {"USDC": 2000.0, "pUSD": 1000.0}},
            "spatha-keeper": {"arc": {"USDC": 2000.0}, "hyperliquid": {"USDC": 1000.0}},
            "agros-keeper": {"arc": {"USDC": 3000.0, "USYC": 0.0}},
            "trace-keeper": {"arc": {"USDC": 50.0}},
        }
        for wallet_id, chains in seed.items():
            for chain, tokens in chains.items():
                for token, amt in tokens.items():
                    self._balances[wallet_id][chain][token] = amt

        self._next_sig = 1

    async def sign_user_op(self, wallet_id: str, user_op: dict) -> dict:
        # TODO real impl: POST /v1/w3s/developer/sign/userOperation
        signed = dict(user_op)
        signed["signature"] = f"0xmocksig{self._next_sig:062x}"
        self._next_sig += 1
        return signed

    async def sign_eip712(self, wallet_id: str, typed_data: dict) -> str:
        # TODO real impl: POST /v1/w3s/developer/sign/typedData
        sig = f"0xmocksig{self._next_sig:062x}"
        self._next_sig += 1
        return sig

    async def get_balance(self, wallet_id: str, chain: str) -> dict:
        bal = self._balances[wallet_id][chain]
        return {"USDC": bal["USDC"], "USYC": bal["USYC"], "pUSD": bal["pUSD"]}

    # Helper for mocks to mutate balances (not in Protocol)
    def _adjust(self, wallet_id: str, chain: str, token: str, delta: float) -> None:
        self._balances[wallet_id][chain][token] += delta

    def _peek(self, wallet_id: str, chain: str, token: str) -> float:
        return self._balances[wallet_id][chain][token]


# ---------------------------------------------------------------------------
# Mock USYC
# ---------------------------------------------------------------------------

class MockUSYC(USYCAdapter):
    """Mock USYC.

    Real testnet flow (per docs.arc.io):
      1. Request allowlisting via Circle support ticket (Day 1)
      2. Get testnet USDC from Circle Faucet
      3. Call USYC Teller contract on Arc testnet
    """

    def __init__(self, wallets: MockCircleWallets, apy: float = 0.0393):
        self._wallets = wallets
        self._apy = apy
        # NAV per share starts at 1.0 and grows continuously at apy
        self._nav_per_share = 1.0
        self._nav_anchor_ts = time.time()
        # Redemption fee (Circle published: 0.03%)
        self._redemption_fee_bps = 3
        self._next_tx = 1

    def _current_nav(self) -> float:
        # Continuous compounding for cleanliness
        elapsed = time.time() - self._nav_anchor_ts
        years = elapsed / (365.25 * 24 * 3600)
        import math
        return self._nav_per_share * math.exp(self._apy * years)

    async def subscribe(self, wallet_id: str, amount_usdc: float) -> SubscribeReceipt:
        if self._wallets._peek(wallet_id, "arc", "USDC") < amount_usdc:
            raise ValueError("Insufficient USDC on Arc for USYC subscribe")
        nav = self._current_nav()
        usyc_out = amount_usdc / nav
        self._wallets._adjust(wallet_id, "arc", "USDC", -amount_usdc)
        self._wallets._adjust(wallet_id, "arc", "USYC", usyc_out)

        tx_hash = f"0xmockusyc{self._next_tx:060x}"
        self._next_tx += 1
        return SubscribeReceipt(
            usdc_in=amount_usdc,
            usyc_out=usyc_out,
            nav=nav,
            tx_hash=tx_hash,
        )

    async def redeem(self, wallet_id: str, amount_usyc: float) -> RedeemReceipt:
        if self._wallets._peek(wallet_id, "arc", "USYC") < amount_usyc:
            raise ValueError("Insufficient USYC to redeem")
        nav = self._current_nav()
        gross_usdc = amount_usyc * nav
        fee = gross_usdc * (self._redemption_fee_bps / 10000)
        net_usdc = gross_usdc - fee

        self._wallets._adjust(wallet_id, "arc", "USYC", -amount_usyc)
        self._wallets._adjust(wallet_id, "arc", "USDC", net_usdc)

        tx_hash = f"0xmockusyc{self._next_tx:060x}"
        self._next_tx += 1
        return RedeemReceipt(
            usyc_in=amount_usyc,
            usdc_out=net_usdc,
            fee=fee,
            tx_hash=tx_hash,
        )

    async def get_balance(self, wallet_id: str) -> float:
        # USYC tokens, not USD value
        return self._wallets._peek(wallet_id, "arc", "USYC")

    async def get_current_yield_apy(self) -> float:
        return self._apy

    async def get_nav_per_share(self) -> float:
        return self._current_nav()


# ---------------------------------------------------------------------------
# Mock Gateway
# ---------------------------------------------------------------------------

class MockGateway(GatewayAdapter):
    def __init__(self, wallets: MockCircleWallets):
        self._wallets = wallets
        self._next_tx = 1

    async def transfer(
        self,
        wallet_id: str,
        amount_usdc: float,
        src_chain: str,
        dst_chain: str,
    ) -> TransferReceipt:
        if src_chain == dst_chain:
            raise ValueError("src_chain must differ from dst_chain")
        if self._wallets._peek(wallet_id, src_chain, "USDC") < amount_usdc:
            raise ValueError(f"Insufficient USDC on {src_chain}")

        # Simulate <500ms transfer
        elapsed_ms = random.randint(200, 480)
        await asyncio.sleep(elapsed_ms / 1000)

        self._wallets._adjust(wallet_id, src_chain, "USDC", -amount_usdc)
        self._wallets._adjust(wallet_id, dst_chain, "USDC", amount_usdc)

        src_tx = f"0xmocksrctx{self._next_tx:060x}"
        self._next_tx += 1
        dst_tx = f"0xmockdsttx{self._next_tx:060x}"
        self._next_tx += 1

        return TransferReceipt(
            amount_usdc=amount_usdc,
            src_chain=src_chain,
            dst_chain=dst_chain,
            src_tx=src_tx,
            dst_tx=dst_tx,
            elapsed_ms=elapsed_ms,
        )

    async def get_unified_balance(self, wallet_id: str) -> float:
        total = 0.0
        for chain_balances in self._wallets._balances[wallet_id].values():
            total += chain_balances["USDC"]
        return total


# ---------------------------------------------------------------------------
# Mock Nanopayments
# ---------------------------------------------------------------------------

class MockNanopayment(NanopaymentAdapter):
    """Mock Nanopayment + IPFS pin.

    Real impl: pin via Pinata/web3.storage with x402 paywall.
    """

    def __init__(self, wallets: MockCircleWallets, payer_wallet: str = "trace-keeper"):
        self._wallets = wallets
        self._payer = payer_wallet
        self._pinned: dict[str, bytes] = {}
        self._next_cid_seq = 1

    async def pay(self, recipient: str, amount_usdc: float, memo: str = "") -> str:
        if self._wallets._peek(self._payer, "arc", "USDC") < amount_usdc:
            # Don't fail: nanopayments are batch-settled in real life
            pass
        else:
            self._wallets._adjust(self._payer, "arc", "USDC", -amount_usdc)
        return f"nanopay-{int(time.time() * 1000)}"

    async def pin_to_ipfs(self, content_bytes: bytes, max_price_usdc: float = 0.005) -> str:
        # Pin cost ~$0.001 per pin (Pinata-like)
        price = 0.001
        if price > max_price_usdc:
            raise ValueError(f"Pin price {price} exceeds max {max_price_usdc}")
        await self.pay("ipfs-pin-provider", price, "trace pin")

        # Generate a deterministic CID from content hash for verifiability
        import hashlib
        digest = hashlib.sha256(content_bytes).hexdigest()
        # CIDv1 base32-ish format (not strictly valid but stable + recognizable)
        cid = f"bafy{digest[:48]}"
        self._pinned[cid] = content_bytes
        return cid

    def _fetch(self, cid: str) -> Optional[bytes]:
        """Test/demo helper — fetch a pinned body by CID."""
        return self._pinned.get(cid)


# ---------------------------------------------------------------------------
# Mock Arc RPC
# ---------------------------------------------------------------------------

class MockArc(ArcAdapter):
    def __init__(self):
        self._block = 1_000_000
        self._next_tx_seq = 1
        # Per-contract per-function call counter — useful for inspecting state
        self._call_log: list[dict] = []

    async def call_contract(
        self,
        contract_addr: str,
        function: str,
        args: list,
    ) -> bytes:
        self._call_log.append({
            "type": "call",
            "contract": contract_addr,
            "function": function,
            "args": args,
            "block": self._block,
        })
        # Return empty bytes; tests can inspect the log
        return b""

    async def submit_tx(
        self,
        wallet_id: str,
        contract_addr: str,
        calldata: bytes,
    ) -> TxReceipt:
        # Simulate sub-second Arc finality
        await asyncio.sleep(random.uniform(0.2, 0.8))
        self._block += 1
        tx_hash = f"0xmockarc{self._next_tx_seq:062x}"
        self._next_tx_seq += 1
        # Gas cost on Arc: ~$0.01 USDC
        return TxReceipt(
            tx_hash=tx_hash,
            block_number=self._block,
            gas_paid_usdc=0.01,
            status="success",
        )

    async def get_block_number(self) -> int:
        return self._block

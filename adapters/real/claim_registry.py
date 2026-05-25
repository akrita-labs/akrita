"""
ClaimRegistryReal — AKRITA Rugpull Oracle on-chain surface (Arc).

Split-signing, mirroring ArcReal:
  - READS  (totalClaims, getClaim, bonds) go directly to Arc JSON-RPC via web3.
  - WRITES (issueClaim, resolve) are signed by the Circle MPC NOMOS keeper
    through CircleWalletsReal.execute_contract; that keeper must be an
    authorized issuer/resolver on the ClaimRegistry (set at deploy time).

Trace anchoring stays in TraceRegistry (ArcReal.commit_trace) — this contract
stores the claim + its two-sided USDC bond market and references the trace hash.
Gated until CLAIM_REGISTRY_ADDR is set (deploy ClaimRegistry first).
"""
from __future__ import annotations

from typing import Any, Optional

from web3 import AsyncHTTPProvider, AsyncWeb3

from adapters.base import TxReceipt
from adapters.real.circle_wallets import CircleWalletsReal
from shared.config import settings


def _hx(v: Any) -> str:
    if isinstance(v, (bytes, bytearray)):
        h = v.hex()
        return h if h.startswith("0x") else "0x" + h
    s = str(v)
    return s if s.startswith("0x") else "0x" + s


_STATUS = {0: "open", 1: "rugged", 2: "safe"}

# Minimal ABI — only what the oracle reads/writes on ClaimRegistry.
CLAIM_REGISTRY_ABI = [
    {
        "type": "function",
        "name": "totalClaims",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "getClaim",
        "stateMutability": "view",
        "inputs": [{"name": "claimId", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "tokenId", "type": "bytes32"},
                    {"name": "sourceCommit", "type": "bytes32"},
                    {"name": "traceHash", "type": "bytes32"},
                    {"name": "ipfsCid", "type": "string"},
                    {"name": "issuer", "type": "address"},
                    {"name": "issuedAt", "type": "uint64"},
                    {"name": "window", "type": "uint64"},
                    {"name": "dropThresholdBps", "type": "uint16"},
                    {"name": "status", "type": "uint8"},
                    {"name": "resolvedAt", "type": "uint64"},
                ],
            }
        ],
    },
    {
        "type": "function",
        "name": "bonds",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "uint256"}],
        "outputs": [
            {"name": "forStake", "type": "uint256"},
            {"name": "againstStake", "type": "uint256"},
        ],
    },
    {
        "type": "function",
        "name": "bondToken",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
]

# Minimal ERC-20 surface for the bond token (USDC on Arc): read the staker balance
# and approve the registry before a stake.
_ERC20_ABI = [
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "allowance",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]


class ClaimRegistryReal:
    def __init__(self, wallets: CircleWalletsReal) -> None:
        self._wallets = wallets
        self._w3 = AsyncWeb3(AsyncHTTPProvider(settings.arc_rpc_url))
        self._addr = (
            AsyncWeb3.to_checksum_address(settings.claim_registry_addr)
            if settings.claim_registry_addr
            else ""
        )

    def _contract(self):
        if not self._addr:
            raise RuntimeError("CLAIM_REGISTRY_ADDR not set — deploy ClaimRegistry first")
        return self._w3.eth.contract(address=self._addr, abi=CLAIM_REGISTRY_ABI)

    def status_label(self, status: int) -> str:
        return _STATUS.get(int(status), "unknown")

    # ----- reads -----------------------------------------------------------

    async def total_claims(self) -> int:
        return int(await self._contract().functions.totalClaims().call())

    async def get_claim(self, claim_id: int) -> Optional[dict]:
        try:
            c = await self._contract().functions.getClaim(int(claim_id)).call()
        except Exception:
            return None
        return {
            "claim_id": int(claim_id),
            "token_id": _hx(c[0]),
            "source_commit": _hx(c[1]),
            "trace_hash": _hx(c[2]),
            "ipfs_cid": c[3],
            "issuer": c[4],
            "issued_at": int(c[5]),
            "window_s": int(c[6]),
            "drop_threshold_bps": int(c[7]),
            "status": self.status_label(c[8]),
            "resolved_at": int(c[9]),
        }

    async def get_bond(self, claim_id: int) -> dict:
        b = await self._contract().functions.bonds(int(claim_id)).call()
        return {"for_stake": int(b[0]), "against_stake": int(b[1])}

    # ----- writes (via Circle NOMOS keeper) -------------------------------

    async def issue_claim(
        self,
        token_id: str,
        source_commit: str,
        trace_hash: str,
        ipfs_cid: str,
        window_s: int,
        drop_threshold_bps: int,
    ) -> TxReceipt:
        """Register a signed rug-risk claim. The trace must already be anchored
        (ArcReal.commit_trace) so `trace_hash` resolves in TraceRegistry."""
        if not self._addr:
            raise RuntimeError("CLAIM_REGISTRY_ADDR not set — deploy ClaimRegistry first")
        wallet_id = self._wallets.wallet_id("pricing-keeper", "ARC-TESTNET")
        return await self._wallets.execute_contract(
            wallet_id=wallet_id,
            contract_address=settings.claim_registry_addr,
            abi_signature="issueClaim(bytes32,bytes32,bytes32,string,uint64,uint16)",
            abi_parameters=[
                token_id,
                source_commit,
                trace_hash,
                ipfs_cid,
                str(int(window_s)),
                str(int(drop_threshold_bps)),
            ],
            blockchain="ARC-TESTNET",
        )

    async def resolve(self, claim_id: int, rugged: bool) -> TxReceipt:
        """Record the outcome (rugged=True → claim resolves TRUE). Resolver-gated."""
        if not self._addr:
            raise RuntimeError("CLAIM_REGISTRY_ADDR not set — deploy ClaimRegistry first")
        wallet_id = self._wallets.wallet_id("pricing-keeper", "ARC-TESTNET")
        return await self._wallets.execute_contract(
            wallet_id=wallet_id,
            contract_address=settings.claim_registry_addr,
            abi_signature="resolve(uint256,bool)",
            abi_parameters=[str(int(claim_id)), bool(rugged)],
            blockchain="ARC-TESTNET",
        )

    # ----- bond market (SPATHA conviction stake) --------------------------

    async def bond_token(self) -> str:
        """The ERC-20 used for bonds (USDC on Arc)."""
        return await self._contract().functions.bondToken().call()

    async def usdc_balance(self, address: str) -> int:
        """USDC (bond-token) balance of an address, base units (6 decimals)."""
        bt = await self.bond_token()
        erc20 = self._w3.eth.contract(address=AsyncWeb3.to_checksum_address(bt), abi=_ERC20_ABI)
        return int(await erc20.functions.balanceOf(AsyncWeb3.to_checksum_address(address)).call())

    async def stake(
        self,
        claim_id: int,
        backs_claim: bool,
        amount_base_units: int,
        *,
        wallet_role: str = "hedge-keeper",
        approve: bool = True,
    ) -> dict:
        """SPATHA stakes its conviction on a claim: `backs_claim=True` bets the
        token rugs, False bets it holds. `amount_base_units` is USDC (6 decimals).

        Two writes signed by the SPATHA (hedge) Circle MPC keeper: `approve` the
        registry to pull the USDC, then `stake`. Gated on that wallet actually
        holding USDC on Arc — raises if unfunded so the caller reports honestly.
        """
        if not self._addr:
            raise RuntimeError("CLAIM_REGISTRY_ADDR not set — deploy ClaimRegistry first")
        amount = int(amount_base_units)
        if amount <= 0:
            raise ValueError("stake amount must be positive")
        wallet_id = self._wallets.wallet_id(wallet_role, "ARC-TESTNET")
        out: dict = {}
        if approve:
            bt = await self.bond_token()
            approve_rcpt = await self._wallets.execute_contract(
                wallet_id=wallet_id,
                contract_address=bt,
                abi_signature="approve(address,uint256)",
                abi_parameters=[settings.claim_registry_addr, str(amount)],
                blockchain="ARC-TESTNET",
            )
            out["approve_tx"] = getattr(approve_rcpt, "tx_hash", None)
        stake_rcpt = await self._wallets.execute_contract(
            wallet_id=wallet_id,
            contract_address=settings.claim_registry_addr,
            abi_signature="stake(uint256,bool,uint256)",
            abi_parameters=[str(int(claim_id)), bool(backs_claim), str(amount)],
            blockchain="ARC-TESTNET",
        )
        out["stake_tx"] = getattr(stake_rcpt, "tx_hash", None)
        out["claim_id"] = int(claim_id)
        out["backs_claim"] = bool(backs_claim)
        out["amount_base_units"] = amount
        return out

    async def withdraw(self, claim_id: int, *, wallet_role: str = "hedge-keeper") -> TxReceipt:
        """Withdraw a settled bond (winners get stake + pro-rata share of the
        losing pool; losers are slashed). Idempotent per staker on-chain."""
        if not self._addr:
            raise RuntimeError("CLAIM_REGISTRY_ADDR not set — deploy ClaimRegistry first")
        wallet_id = self._wallets.wallet_id(wallet_role, "ARC-TESTNET")
        return await self._wallets.execute_contract(
            wallet_id=wallet_id,
            contract_address=settings.claim_registry_addr,
            abi_signature="withdraw(uint256)",
            abi_parameters=[str(int(claim_id))],
            blockchain="ARC-TESTNET",
        )

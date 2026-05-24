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

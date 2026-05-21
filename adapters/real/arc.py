"""
ArcReal — Arc L1 read/write surface.

Split signing model:
  - READS  (block number, contract view calls, event logs) go directly to
    the Arc JSON-RPC via web3.py. No signing, no Circle round-trip.
  - WRITES (commitTrace) are signed by the Circle MPC trace-keeper wallet
    through CircleWalletsReal.execute_contract. The trace-keeper is an
    authorized keeper on the TraceRegistry (set at deploy time).

Arc is EVM-compatible with USDC as native gas. We talk standard JSON-RPC.
"""
from __future__ import annotations

from typing import Any

from web3 import AsyncHTTPProvider, AsyncWeb3

from adapters.base import TxReceipt
from adapters.real.circle_wallets import CircleWalletsReal
from shared.config import settings


# Minimal ABI fragments — only what ArcReal reads/writes on TraceRegistry.
TRACE_REGISTRY_ABI = [
    {
        "type": "function",
        "name": "commitTrace",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "decisionId", "type": "uint256"},
            {"name": "traceHash", "type": "bytes32"},
            {"name": "ipfsCid", "type": "string"},
        ],
        "outputs": [{"name": "commitIndex", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "verifyTrace",
        "stateMutability": "view",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "decisionId", "type": "uint256"},
            {"name": "traceBody", "type": "bytes"},
        ],
        "outputs": [{"name": "ok", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "getCommit",
        "stateMutability": "view",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "decisionId", "type": "uint256"},
        ],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "agentId", "type": "uint256"},
                    {"name": "decisionId", "type": "uint256"},
                    {"name": "traceHash", "type": "bytes32"},
                    {"name": "ipfsCid", "type": "string"},
                    {"name": "timestamp", "type": "uint64"},
                ],
            }
        ],
    },
    {
        "type": "function",
        "name": "totalCommits",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "authorizedKeepers",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
]

# NOMOS=1, SPATHA=2, AGROS=3 (matches BuilderRegistry agent IDs).
_AGENT_ID = {"nomos": 1, "spatha": 2, "agros": 3}


class ArcReal:
    def __init__(self, wallets: CircleWalletsReal) -> None:
        self._wallets = wallets
        self._w3 = AsyncWeb3(AsyncHTTPProvider(settings.arc_rpc_url))
        self._trace_registry_addr = (
            AsyncWeb3.to_checksum_address(settings.trace_registry_addr)
            if settings.trace_registry_addr
            else ""
        )

    def agent_id(self, role: str) -> int:
        return _AGENT_ID.get(role.replace("-keeper", "").strip().lower(), 0)

    # ----- reads -----------------------------------------------------------

    async def get_block_number(self) -> int:
        return int(await self._w3.eth.block_number)

    async def get_chain_id(self) -> int:
        return int(await self._w3.eth.chain_id)

    def _trace_registry(self):
        if not self._trace_registry_addr:
            raise RuntimeError("TRACE_REGISTRY_ADDR not set — deploy contracts first")
        return self._w3.eth.contract(address=self._trace_registry_addr, abi=TRACE_REGISTRY_ABI)

    async def total_commits(self) -> int:
        return int(await self._trace_registry().functions.totalCommits().call())

    async def is_authorized_keeper(self, address: str) -> bool:
        addr = AsyncWeb3.to_checksum_address(address)
        return bool(await self._trace_registry().functions.authorizedKeepers(addr).call())

    async def get_trace_commit(self, agent_id: int, decision_id: int) -> dict[str, Any] | None:
        try:
            c = await self._trace_registry().functions.getCommit(agent_id, decision_id).call()
        except Exception:
            return None
        return {
            "agent_id": int(c[0]),
            "decision_id": int(c[1]),
            "trace_hash": "0x" + c[2].hex() if isinstance(c[2], (bytes, bytearray)) else c[2],
            "ipfs_cid": c[3],
            "timestamp": int(c[4]),
        }

    async def verify_trace_onchain(self, agent_id: int, decision_id: int, body_bytes: bytes) -> bool:
        return bool(
            await self._trace_registry().functions.verifyTrace(agent_id, decision_id, body_bytes).call()
        )

    # ----- writes (via Circle trace-keeper) -------------------------------

    async def commit_trace(
        self,
        agent_id: int,
        decision_id: int,
        trace_hash_hex: str,
        ipfs_cid: str,
    ) -> TxReceipt:
        """Commit (agentId, decisionId, sha256 hash, CID) to TraceRegistry,
        signed by the Circle MPC trace-keeper wallet."""
        if not self._trace_registry_addr:
            raise RuntimeError("TRACE_REGISTRY_ADDR not set — deploy contracts first")
        wallet_id = self._wallets.wallet_id("trace-keeper", "ARC-TESTNET")
        return await self._wallets.execute_contract(
            wallet_id=wallet_id,
            contract_address=settings.trace_registry_addr,
            abi_signature="commitTrace(uint256,uint256,bytes32,string)",
            abi_parameters=[str(agent_id), str(decision_id), trace_hash_hex, ipfs_cid],
            blockchain="ARC-TESTNET",
        )

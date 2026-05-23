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

import asyncio
import json
import pathlib
from typing import Any

from eth_account import Account
from web3 import AsyncHTTPProvider, AsyncWeb3

from adapters.base import TxReceipt
from adapters.real.circle_wallets import CircleWalletsReal
from shared.config import settings


def _hx(v: Any) -> str:
    """Normalise bytes / HexBytes / str to a 0x-prefixed hex string."""
    if isinstance(v, (bytes, bytearray)):
        h = v.hex()
        return h if h.startswith("0x") else "0x" + h
    s = str(v)
    return s if s.startswith("0x") else "0x" + s


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

# Minimal ABI for the BuilderRegistry — registration (write, owner-signed)
# plus the views the onboarding flow + leaderboard read.
BUILDER_REGISTRY_ABI = [
    {
        "type": "function",
        "name": "registerAgent",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "builderCode", "type": "bytes32"},
            {"name": "controllerWallet", "type": "address"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "getBuilderCode",
        "stateMutability": "view",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
    {
        "type": "function",
        "name": "byBuilderCode",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "isActive",
        "stateMutability": "view",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "owner",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "type": "function",
        "name": "agents",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "uint256"}],
        "outputs": [
            {"name": "builderCode", "type": "bytes32"},
            {"name": "controllerWallet", "type": "address"},
            {"name": "reputation", "type": "uint64"},
            {"name": "registeredAt", "type": "uint64"},
            {"name": "active", "type": "bool"},
        ],
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
        self._builder_registry_addr = (
            AsyncWeb3.to_checksum_address(settings.builder_registry_addr)
            if settings.builder_registry_addr
            else ""
        )
        self._owner_acct = None
        # Serialise owner-signed writes so concurrent registrations don't
        # collide on the EOA's transaction nonce.
        self._owner_lock = asyncio.Lock()

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

    # ----- BuilderRegistry reads ------------------------------------------

    def _builder_registry(self):
        if not self._builder_registry_addr:
            raise RuntimeError("BUILDER_REGISTRY_ADDR not set — deploy contracts first")
        return self._w3.eth.contract(
            address=self._builder_registry_addr, abi=BUILDER_REGISTRY_ABI
        )

    async def builder_code_for(self, agent_id: int) -> str:
        """On-chain builder code registered for an agentId (0x000…0 if none)."""
        code = await self._builder_registry().functions.getBuilderCode(int(agent_id)).call()
        return _hx(code)

    async def is_agent_registered(self, agent_id: int) -> bool:
        a = await self._builder_registry().functions.agents(int(agent_id)).call()
        return int(a[3]) != 0  # registeredAt != 0

    async def agent_id_for_code(self, builder_code_hex: str) -> int:
        code = bytes.fromhex(builder_code_hex[2:].rjust(64, "0"))
        return int(await self._builder_registry().functions.byBuilderCode(code).call())

    # ----- BuilderRegistry write (owner-signed, raw key) ------------------

    def _owner_account(self):
        """Lazily load the BuilderRegistry owner EOA from its keyfile."""
        if self._owner_acct is None:
            p = pathlib.Path(settings.arc_owner_keyfile)
            if not p.is_absolute():
                p = pathlib.Path(__file__).resolve().parents[2] / settings.arc_owner_keyfile
            data = json.loads(p.read_text())
            self._owner_acct = Account.from_key(data["privateKey"])
        return self._owner_acct

    async def register_builder(
        self, agent_id: int, builder_code_hex: str, controller_addr: str
    ) -> TxReceipt:
        """Register a (agentId -> builderCode, controllerWallet) mapping on the
        BuilderRegistry. `registerAgent` is onlyOwner and ownership is fixed at
        deploy, so this is signed with the owner EOA's raw key (not Circle MPC).
        Serialised under a lock to keep the EOA nonce monotonic."""
        if not self._builder_registry_addr:
            raise RuntimeError("BUILDER_REGISTRY_ADDR not set — deploy contracts first")
        acct = self._owner_account()
        contract = self._builder_registry()
        code_bytes = bytes.fromhex(builder_code_hex[2:].rjust(64, "0"))
        controller = AsyncWeb3.to_checksum_address(controller_addr)
        fn = contract.functions.registerAgent(int(agent_id), code_bytes, controller)

        async with self._owner_lock:
            nonce = await self._w3.eth.get_transaction_count(acct.address, "pending")
            try:
                gas = int(await fn.estimate_gas({"from": acct.address}) * 1.3)
            except Exception:
                gas = 250_000
            gas_price = int(await self._w3.eth.gas_price)
            tx = await fn.build_transaction(
                {
                    "from": acct.address,
                    "nonce": nonce,
                    "chainId": int(settings.arc_chain_id),
                    "gas": gas,
                    "gasPrice": gas_price,
                }
            )
            signed = acct.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
            tx_hash = await self._w3.eth.send_raw_transaction(raw)
            receipt = await self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        return TxReceipt(
            tx_hash=_hx(tx_hash),
            block_number=int(receipt["blockNumber"]),
            gas_paid_usdc=float(receipt["gasUsed"]) * gas_price / 1e18,
            status="success" if int(receipt["status"]) == 1 else "failed",
        )

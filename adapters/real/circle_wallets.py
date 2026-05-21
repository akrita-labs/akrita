"""
CircleWalletsReal — the signing + execution backbone.

Every Arc/Polygon write in AKRITA that must be signed by a keeper wallet
routes through here. The wallets are Circle Developer-Controlled (MPC):
there is no local private key, so we authorize signing by passing the
registered entity secret and let Circle sign server-side.

The Circle SDK is synchronous; we wrap its blocking calls in
`asyncio.to_thread` so they don't stall the event loop, and poll
transaction state with `asyncio.sleep`.

Shared by ArcReal (trace commits), and later PolymarketReal (EIP-712
order signing), GatewayReal, USYCReal, and AGROS balance reads.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from circle.web3 import developer_controlled_wallets as dcw
from circle.web3 import utils

from adapters.base import TxReceipt
from shared.config import settings


# Map a logical keeper role + chain to the configured Circle wallet ID.
_WALLET_ID_BY_ROLE_CHAIN: dict[tuple[str, str], str] = {}
_WALLET_ADDR_BY_ROLE: dict[str, str] = {}


def _build_wallet_maps() -> None:
    _WALLET_ID_BY_ROLE_CHAIN.update(
        {
            ("pricing", "ARC-TESTNET"): settings.pricing_wallet_id_arc,
            ("pricing", "MATIC-AMOY"): settings.pricing_wallet_id_matic,
            ("hedge", "ARC-TESTNET"): settings.hedge_wallet_id_arc,
            ("hedge", "MATIC-AMOY"): settings.hedge_wallet_id_matic,
            ("treasury", "ARC-TESTNET"): settings.treasury_wallet_id_arc,
            ("treasury", "MATIC-AMOY"): settings.treasury_wallet_id_matic,
            ("trace", "ARC-TESTNET"): settings.trace_wallet_id_arc,
            ("trace", "MATIC-AMOY"): settings.trace_wallet_id_matic,
        }
    )
    _WALLET_ADDR_BY_ROLE.update(
        {
            "pricing": settings.pricing_wallet_addr,
            "hedge": settings.hedge_wallet_addr,
            "treasury": settings.treasury_wallet_addr,
            "trace": settings.trace_wallet_addr,
        }
    )


# Accept the legacy "<role>-keeper" aliases used by the trace pipeline.
def _normalize_role(role: str) -> str:
    return role.replace("-keeper", "").strip().lower()


POLL_INTERVAL_SEC = 3
POLL_TIMEOUT_SEC = 180
_TERMINAL_OK = {"CONFIRMED", "COMPLETE"}
_TERMINAL_FAIL = {"FAILED", "CANCELLED", "DENIED"}


class CircleWalletsReal:
    """Circle Developer-Controlled Wallets client."""

    def __init__(self) -> None:
        if not settings.circle_api_key or settings.circle_api_key.count(":") != 2:
            raise RuntimeError("CIRCLE_API_KEY missing/malformed — cannot build CircleWalletsReal")
        secret_path = Path(settings.circle_entity_secret_file)
        if not secret_path.is_absolute():
            secret_path = Path(__file__).resolve().parents[2] / secret_path
        if not secret_path.exists():
            raise RuntimeError(f"Circle entity secret not found at {secret_path}")
        self._entity_secret = secret_path.read_text().strip()
        if not _WALLET_ID_BY_ROLE_CHAIN:
            _build_wallet_maps()
        self._client = utils.init_developer_controlled_wallets_client(
            api_key=settings.circle_api_key,
            entity_secret=self._entity_secret,
        )
        self._tx_api = dcw.TransactionsApi(self._client)
        self._wallets_api = dcw.WalletsApi(self._client)

    # ----- wallet resolution ----------------------------------------------

    def wallet_id(self, role: str, chain: str = "ARC-TESTNET") -> str:
        wid = _WALLET_ID_BY_ROLE_CHAIN.get((_normalize_role(role), chain), "")
        if not wid:
            raise KeyError(f"no Circle wallet for role={role!r} chain={chain!r}")
        return wid

    def wallet_address(self, role: str) -> str:
        addr = _WALLET_ADDR_BY_ROLE.get(_normalize_role(role), "")
        if not addr:
            raise KeyError(f"no address for role={role!r}")
        return addr

    # ----- transaction polling --------------------------------------------

    async def wait_for_tx(self, tx_id: str) -> dict[str, Any]:
        elapsed = 0
        while elapsed < POLL_TIMEOUT_SEC:
            resp = await asyncio.to_thread(self._tx_api.get_transaction, id=tx_id)
            tx = resp.data.transaction
            state = getattr(tx.state, "value", str(tx.state))
            if state in _TERMINAL_OK:
                return tx.model_dump()
            if state in _TERMINAL_FAIL:
                raise RuntimeError(
                    f"Circle tx {tx_id} failed: state={state} "
                    f"reason={getattr(tx, 'error_reason', None)} "
                    f"detail={getattr(tx, 'error_details', None)}"
                )
            await asyncio.sleep(POLL_INTERVAL_SEC)
            elapsed += POLL_INTERVAL_SEC
        raise TimeoutError(f"Circle tx {tx_id} did not confirm within {POLL_TIMEOUT_SEC}s")

    # ----- contract execution (the workhorse) -----------------------------

    async def execute_contract(
        self,
        wallet_id: str,
        contract_address: str,
        abi_signature: str,
        abi_parameters: list,
        *,
        blockchain: str = "ARC-TESTNET",
        wait: bool = True,
    ) -> TxReceipt:
        """Call a contract function, signed by `wallet_id`. Returns a receipt
        once confirmed (or a pending receipt if wait=False)."""
        wrapped = [dcw.AbiParametersInner(p) for p in abi_parameters]
        req = dcw.CreateContractExecutionTransactionForDeveloperRequest(
            idempotencyKey=str(uuid.uuid4()),
            entitySecretCiphertext="",  # auto-filled by SDK wrapper
            walletId=wallet_id,
            contractAddress=contract_address,
            abiFunctionSignature=abi_signature,
            abiParameters=wrapped,
            feeLevel=dcw.FeeLevel.MEDIUM,
        )
        resp = await asyncio.to_thread(
            self._tx_api.create_developer_transaction_contract_execution, req
        )
        tx_id = resp.data.id
        if not wait:
            return TxReceipt(tx_hash="", block_number=0, gas_paid_usdc=0.0, status="pending")
        tx = await self.wait_for_tx(tx_id)
        return TxReceipt(
            tx_hash=tx.get("tx_hash") or "",
            block_number=int(tx.get("block_height") or 0),
            gas_paid_usdc=float(tx.get("network_fee") or 0.0),
            status="success",
        )

    # ----- ERC-20 / native transfer ---------------------------------------

    async def transfer_erc20(
        self,
        wallet_id: str,
        token_address: str,
        to_address: str,
        amount_base_units: int,
        *,
        blockchain: str = "ARC-TESTNET",
    ) -> TxReceipt:
        """Transfer an ERC-20 token via a contract execution (transfer(to,amount))."""
        return await self.execute_contract(
            wallet_id,
            token_address,
            "transfer(address,uint256)",
            [to_address, str(amount_base_units)],
            blockchain=blockchain,
        )

    # ----- EIP-712 signing (used by PolymarketReal later) ------------------

    async def sign_eip712(self, wallet_id: str, typed_data: dict) -> str:
        import json
        api = dcw.SigningApi(self._client)
        req = dcw.SignTypedDataRequest(
            walletId=wallet_id,
            data=json.dumps(typed_data),
            entitySecretCiphertext="",  # auto-filled
        )
        resp = await asyncio.to_thread(api.sign_typed_data, req)
        return resp.data.signature

    async def sign_user_op(self, wallet_id: str, user_op: dict) -> dict:
        raise NotImplementedError("sign_user_op not needed for EOA wallets")

    # ----- balances --------------------------------------------------------

    async def get_balance(self, wallet_id: str, chain: str) -> dict:
        """Returns {'USDC': float, 'USYC': float, 'pUSD': float}."""
        resp = await asyncio.to_thread(
            self._wallets_api.list_wallet_balance, id=wallet_id
        )
        out = {"USDC": 0.0, "USYC": 0.0, "pUSD": 0.0}
        for tb in resp.data.token_balances or []:
            sym = getattr(getattr(tb, "token", None), "symbol", "") or ""
            try:
                out[sym] = float(tb.amount)
            except (TypeError, ValueError):
                pass
        return out

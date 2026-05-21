"""
GatewayReal — Circle Gateway cross-chain USDC (unified balance, <500ms).

Gateway is a *contract-level* integration: there is no Python SDK. The flow
is deposit -> burn -> mint:

  1. Deposit USDC into the Gateway Wallet contract on any supported chain.
     Each deposit adds to a single unified balance (an accounting layer over
     per-chain USDC).
  2. To move funds, build a `BurnIntent` (an EIP-712 `TransferSpec`) naming a
     source domain (chain to burn from) and destination domain (chain to mint
     on), sign it, and POST it to the Gateway `/transfer` REST API.
  3. The API returns an attestation + operator signature; call
     `gatewayMint(bytes,bytes)` on the destination chain's Gateway Minter to
     receive USDC. End-to-end is sub-second because it does not wait on source
     finality.

Split model (mirrors the rest of adapters/real):
  - READ  (`get_unified_balance`) is a public REST call — POST /balances with
    {domain, depositor} tuples. Works live; returns 0 until USDC is deposited.
  - WRITE (`transfer`) signs the burn intent with the Circle MPC keeper wallet
    via CircleWalletsReal.sign_eip712, then mints via
    CircleWalletsReal.execute_contract("gatewayMint(bytes,bytes)").

Provisioning gate (why transfer is currently blocked):
  The unified balance is funded only by on-chain deposits into the Gateway
  Wallet contract. AKRITA has not yet seeded the treasury's Gateway balance,
  so a transfer would burn from a zero balance and the API would reject it.
  Rather than fake a transfer, `transfer` verifies the live source-domain
  unified balance first and raises a clear, actionable RuntimeError when it is
  insufficient (the same posture as Polymarket's collateral gate). Once the
  treasury deposits USDC into the Gateway Wallet on the source chain, the same
  code path executes the real burn + mint.

References:
  Addresses + domains: Circle Gateway docs (testnet). Wallet/Minter are the
  same across all EVM testnet chains. Transfer + balance request shapes match
  developers.circle.com/gateway. Arc tutorial: access-usdc-crosschain.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

from adapters.base import TransferReceipt
from adapters.real.circle_wallets import CircleWalletsReal
from shared.config import settings


# Gateway testnet contract addresses (identical across EVM testnet chains).
GATEWAY_WALLET_ADDR = "0x0077777d7EBA4688BDeF3E311b846F25870A19B9"
GATEWAY_MINTER_ADDR = "0x0022222ABE238Cc2C7Bb1f21003F0a260052475B"

# USDC base units (6 decimals on every Gateway chain — never 18).
USDC_DECIMALS = 6


# Friendly chain name -> (Gateway domain id, Circle Wallets blockchain id, USDC
# address on that chain). Testnet domains per Circle Gateway docs; Arc = 26.
_CHAIN_META: dict[str, dict[str, Any]] = {
    "arc": {
        "domain": 26,
        "wallet_chain": "ARC-TESTNET",
        "usdc": "0x3600000000000000000000000000000000000000",
    },
    "polygon": {
        "domain": 7,  # Polygon Amoy
        "wallet_chain": "MATIC-AMOY",
        "usdc": "0x41E94Eb019C0762f9Bfcf9Fb1E58725BfB0e7582",
    },
    "base": {
        "domain": 6,  # Base Sepolia
        "wallet_chain": "BASE-SEPOLIA",
        "usdc": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    },
    "ethereum": {
        "domain": 0,  # Ethereum Sepolia
        "wallet_chain": "ETH-SEPOLIA",
        "usdc": "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238",
    },
    "avalanche": {
        "domain": 1,  # Avalanche Fuji
        "wallet_chain": "AVAX-FUJI",
        "usdc": "0x5425890298aed601595a70AB815c96711a31Bc65",
    },
}

# EIP-712 type definitions for the Gateway burn intent. These MUST match the
# Gateway spec exactly — field names, types, and ordering are load-bearing for
# the signature to verify. Do not reorder or rename.
_EIP712_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
    ],
    "TransferSpec": [
        {"name": "version", "type": "uint32"},
        {"name": "sourceDomain", "type": "uint32"},
        {"name": "destinationDomain", "type": "uint32"},
        {"name": "sourceContract", "type": "bytes32"},
        {"name": "destinationContract", "type": "bytes32"},
        {"name": "sourceToken", "type": "bytes32"},
        {"name": "destinationToken", "type": "bytes32"},
        {"name": "sourceDepositor", "type": "bytes32"},
        {"name": "destinationRecipient", "type": "bytes32"},
        {"name": "sourceSigner", "type": "bytes32"},
        {"name": "destinationCaller", "type": "bytes32"},
        {"name": "value", "type": "uint256"},
        {"name": "salt", "type": "bytes32"},
        {"name": "hookData", "type": "bytes"},
    ],
    "BurnIntent": [
        {"name": "maxBlockHeight", "type": "uint256"},
        {"name": "maxFee", "type": "uint256"},
        {"name": "spec", "type": "TransferSpec"},
    ],
}
_EIP712_DOMAIN = {"name": "GatewayWallet", "version": "1"}
_ZERO_ADDR = "0x0000000000000000000000000000000000000000"
_MAX_UINT256 = (1 << 256) - 1


def _addr_to_bytes32(address: str) -> str:
    return "0x" + address.lower().removeprefix("0x").rjust(64, "0")


def _chain(name: str) -> dict[str, Any]:
    key = name.strip().lower()
    # Tolerate Circle-style identifiers as well as friendly names.
    aliases = {
        "arc-testnet": "arc",
        "matic-amoy": "polygon",
        "matic": "polygon",
        "polygon-amoy": "polygon",
        "base-sepolia": "base",
        "eth-sepolia": "ethereum",
        "eth": "ethereum",
        "avax-fuji": "avalanche",
        "avax": "avalanche",
    }
    key = aliases.get(key, key)
    if key not in _CHAIN_META:
        raise ValueError(
            f"unsupported Gateway chain {name!r}; known: {sorted(_CHAIN_META)}"
        )
    return _CHAIN_META[key]


class GatewayReal:
    def __init__(self, wallets: CircleWalletsReal) -> None:
        self._wallets = wallets
        self._base_url = settings.gateway_api_url.rstrip("/")

    # ----- reads (public REST) --------------------------------------------

    async def _balances(self, sources: list[dict[str, Any]]) -> dict[str, float]:
        """POST /balances for one or more {domain, depositor} tuples. Returns a
        {f"{domain}:{depositor.lower()}": balance_usdc} map."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{self._base_url}/balances",
                json={"token": "USDC", "sources": sources},
                headers={"User-Agent": "akrita-agros/0.1", "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        out: dict[str, float] = {}
        for b in data.get("balances", []):
            try:
                key = f"{int(b['domain'])}:{str(b['depositor']).lower()}"
                out[key] = float(b.get("balance", 0.0) or 0.0)
            except (KeyError, TypeError, ValueError):
                continue
        return out

    async def get_unified_balance(self, wallet_id: str) -> float:
        """Total Gateway unified USDC balance across the chains AKRITA uses.

        The unified balance is an accounting layer; the API returns it per
        {domain, depositor}. We sum the treasury depositor's balance across the
        supported source chains. Live read — returns the real (currently 0)
        balance until USDC is deposited into the Gateway Wallet contract.
        """
        depositor = self._depositor_address(wallet_id)
        sources = [
            {"domain": meta["domain"], "depositor": depositor}
            for meta in _CHAIN_META.values()
        ]
        balances = await self._balances(sources)
        return sum(balances.values())

    async def get_domain_balance(self, wallet_id: str, chain: str) -> float:
        """Unified balance attributable to a single source chain (helper used
        to gate transfers and by callers that pick a burn source)."""
        depositor = self._depositor_address(wallet_id)
        meta = _chain(chain)
        balances = await self._balances([{"domain": meta["domain"], "depositor": depositor}])
        return balances.get(f"{meta['domain']}:{depositor.lower()}", 0.0)

    def _depositor_address(self, wallet_id: str) -> str:
        """Map a Circle wallet id to its on-chain depositor address.

        Treasury (AGROS) is the Gateway depositor today. If the id matches the
        configured treasury id we use the treasury address; otherwise fall back
        to the treasury address (the only Gateway-funded wallet).
        """
        if wallet_id and wallet_id == settings.treasury_wallet_id_arc:
            return settings.treasury_wallet_addr
        return settings.treasury_wallet_addr or self._wallets.wallet_address("treasury")

    # ----- writes (Circle-signed burn intent + mint) ----------------------

    async def transfer(
        self,
        wallet_id: str,
        amount_usdc: float,
        src_chain: str,
        dst_chain: str,
    ) -> TransferReceipt:
        """Move `amount_usdc` from `src_chain` to `dst_chain` via Gateway.

        Full flow (executes once the source unified balance is funded):
          1. Build + EIP-712-sign a BurnIntent with the Circle keeper wallet.
          2. POST it to the Gateway /transfer API for an attestation.
          3. gatewayMint(attestation, signature) on the destination chain.

        Gated: refuses with an actionable RuntimeError when the treasury's
        source-domain unified balance is below `amount_usdc`, because Gateway
        burns from deposited balance and AKRITA has not yet seeded it. This is
        a provisioning dependency, not a code gap — depositing USDC into the
        Gateway Wallet on `src_chain` unblocks the same path.
        """
        if amount_usdc <= 0:
            raise ValueError(f"transfer amount must be positive, got {amount_usdc}")
        src = _chain(src_chain)
        dst = _chain(dst_chain)
        depositor = self._depositor_address(wallet_id)

        # Provisioning gate: confirm the source unified balance can cover it.
        available = await self.get_domain_balance(wallet_id, src_chain)
        if available < amount_usdc:
            raise RuntimeError(
                f"Circle Gateway not provisioned for treasury transfers: source "
                f"unified balance on {src_chain} is {available} USDC, need "
                f"{amount_usdc}. Gateway burns from balance deposited into the "
                f"Gateway Wallet ({GATEWAY_WALLET_ADDR}); seed it by depositing "
                f"USDC on {src_chain} (approve + GatewayWallet.deposit), then "
                f"retry. The burn-intent signing + gatewayMint path is wired and "
                f"will execute once funded."
            )

        started = time.monotonic()
        wid = wallet_id or self._wallets.wallet_id("treasury", "ARC-TESTNET")
        signer_addr = depositor
        value_units = int(round(amount_usdc * 10**USDC_DECIMALS))
        max_fee_units = int(round(settings.gateway_max_fee_usdc * 10**USDC_DECIMALS))

        burn_intent = {
            "maxBlockHeight": str(_MAX_UINT256),
            "maxFee": str(max_fee_units),
            "spec": {
                "version": 1,
                "sourceDomain": src["domain"],
                "destinationDomain": dst["domain"],
                "sourceContract": _addr_to_bytes32(GATEWAY_WALLET_ADDR),
                "destinationContract": _addr_to_bytes32(GATEWAY_MINTER_ADDR),
                "sourceToken": _addr_to_bytes32(src["usdc"]),
                "destinationToken": _addr_to_bytes32(dst["usdc"]),
                "sourceDepositor": _addr_to_bytes32(depositor),
                "destinationRecipient": _addr_to_bytes32(depositor),
                "sourceSigner": _addr_to_bytes32(signer_addr),
                "destinationCaller": _addr_to_bytes32(_ZERO_ADDR),
                "value": str(value_units),
                "salt": "0x" + os.urandom(32).hex(),
                "hookData": "0x",
            },
        }
        typed_data = {
            "types": _EIP712_TYPES,
            "domain": _EIP712_DOMAIN,
            "primaryType": "BurnIntent",
            "message": burn_intent,
        }

        # 1) Sign the burn intent with the Circle MPC keeper wallet.
        signature = await self._wallets.sign_eip712(wid, typed_data)

        # 2) Submit to the Gateway transfer API for an attestation.
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/transfer",
                json=[{"burnIntent": burn_intent, "signature": signature}],
                headers={"User-Agent": "akrita-agros/0.1", "Accept": "application/json"},
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Gateway /transfer rejected the burn intent: "
                    f"{resp.status_code} {resp.text[:300]}"
                )
            payload = resp.json()
        attestation = payload.get("attestation")
        operator_sig = payload.get("signature")
        src_burn_tx = payload.get("transferId") or payload.get("burnTxHash") or ""
        if not attestation or not operator_sig:
            raise RuntimeError(
                f"Gateway /transfer returned no attestation/signature: {payload!r}"
            )

        # 3) Mint on the destination chain via the Circle keeper wallet.
        dst_wid = self._wallets.wallet_id("treasury", dst["wallet_chain"])
        mint_receipt = await self._wallets.execute_contract(
            wallet_id=dst_wid,
            contract_address=GATEWAY_MINTER_ADDR,
            abi_signature="gatewayMint(bytes,bytes)",
            abi_parameters=[attestation, operator_sig],
            blockchain=dst["wallet_chain"],
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return TransferReceipt(
            amount_usdc=amount_usdc,
            src_chain=src_chain,
            dst_chain=dst_chain,
            src_tx=str(src_burn_tx),
            dst_tx=mint_receipt.tx_hash,
            elapsed_ms=elapsed_ms,
        )

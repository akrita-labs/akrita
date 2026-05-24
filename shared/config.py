"""
AKRITA orchestrator configuration.

Single typed Settings object loaded from environment variables (and the
project-root `.env` when present). All call sites read from the
process-wide `settings` singleton at the bottom of this file.

Fail-fast philosophy: structural validation (URL shape, hex codes,
required-when-set invariants) happens at import time. Whether a given
credential is *populated* is left to the adapter that needs it — empty
strings here just mean "not configured yet".
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BYTES32_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- Service ----------------------------------------------------
    orchestrator_port: int = 8000
    orchestrator_url: str = "http://localhost:8000"
    trace_sidecar_url: str = "http://trace-sidecar:8787"

    # ---------- Arc network ------------------------------------------------
    arc_rpc_url: str = "https://rpc.testnet.arc.network"
    arc_explorer_url: str = "https://testnet.arcscan.app"
    arc_chain_id: int = 5042002

    # ---------- Polygon ----------------------------------------------------
    polygon_rpc_url: str = "https://polygon-rpc.com"
    polygon_explorer_url: str = "https://polygonscan.com"
    polygon_ws_url: str = ""

    # ---------- Hyperliquid -----------------------------------------------
    hl_url: str = "https://api.hyperliquid-testnet.xyz"
    hl_account_addr: str = ""
    hl_api_wallet_addr: str = ""
    hl_api_wallet_keyfile: str = "secrets/hl_api_wallet.json"

    # ---------- AKRITA contracts (filled by deploy) ------------------------
    trace_registry_addr: str = ""
    builder_registry_addr: str = ""
    # SusdeAcceptance EIP-712 consent registry (AGROS Tier C sUSDe cooldown).
    susde_acceptance_addr: str = ""
    # BuilderRegistry owner EOA keyfile (deployer). registerAgent is onlyOwner
    # and ownership is fixed at construction (no transferOwnership), so on-chain
    # builder registration is signed with this raw key, not a Circle MPC wallet.
    arc_owner_keyfile: str = "secrets/arc_deployer.json"

    # ---------- Polymarket V2 (CLOB V2) -----------------------------------
    poly_builder_code: str = ""
    poly_relayer_url: str = "https://clob.polymarket.com"
    # CLOB V2 chain: 137 = Polygon mainnet, 80002 = Amoy testnet.
    poly_chain_id: int = 137
    poly_api_key: str = ""
    poly_api_secret: str = ""
    poly_api_passphrase: str = ""
    # Operator confirms the signer EOA holds pUSD collateral + allowances.
    poly_collateral_ready: bool = False

    # ---------- Rugpull Oracle (Pivot 1) ----------------------------------
    # ClaimRegistry on Arc (signed rug-risk / freeze claims + bond market).
    claim_registry_addr: str = ""
    # On-chain stablecoin freeze signal (USDT/USDC blacklist events) — primary,
    # zero-coverage-gap source, read via eth_rpc_url. Etherscan key optional
    # (larger historical backfills + tx detail).
    eth_rpc_url: str = "https://eth-pokt.nodies.app"
    etherscan_api_key: str = ""
    freeze_lookback_blocks: int = 90000  # ~2 weeks
    # GoPlus token-security signal: chain to screen + a comma-separated watchlist
    # of token addresses NOMOS screens for rug-risk flags.
    goplus_chain_id: int = 1  # Ethereum mainnet
    goplus_watchlist: str = ""
    claim_window_s: int = 604800  # 7 days
    claim_drop_threshold_bps: int = 5000  # 50%
    # Gateway source chain that funds the Arc bond pool (set when funded).
    bond_source_chain: str = ""
    bond_source_domain: int = 0

    # ---------- Circle -----------------------------------------------------
    circle_api_key: str = ""
    circle_env: Literal["sandbox", "production"] = "sandbox"
    circle_wallet_set_id: str = ""
    circle_entity_secret_file: str = "secrets/circle_entity_secret.txt"

    # ---------- App security ----------------------------------------------
    # Fernet master key (urlsafe-base64, 32 bytes) for encrypting per-user
    # secrets (Polymarket creds, signer keys) at rest. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    akrita_secret_key: str = ""
    # Shared bearer token guarding internal agent<->orchestrator endpoints.
    internal_api_token: str = ""

    # ---------- Keeper wallets (per chain, EOA address shared across) -----
    pricing_wallet_addr: str = ""
    pricing_wallet_id_arc: str = ""
    pricing_wallet_id_matic: str = ""
    hedge_wallet_addr: str = ""
    hedge_wallet_id_arc: str = ""
    hedge_wallet_id_matic: str = ""
    treasury_wallet_addr: str = ""
    treasury_wallet_id_arc: str = ""
    treasury_wallet_id_matic: str = ""
    trace_wallet_addr: str = ""
    trace_wallet_id_arc: str = ""
    trace_wallet_id_matic: str = ""

    # ---------- USYC -------------------------------------------------------
    usyc_wallet_allowlisted: bool = False

    # ---------- Circle Gateway (cross-chain USDC) -------------------------
    # Gateway is a contract-level integration (no Python SDK): deposit into the
    # Gateway Wallet, POST a signed burn intent to this REST API for an
    # attestation, then call gatewayMint on the destination. Testnet default;
    # switch to https://gateway-api.circle.com/v1 for mainnet. The Wallet /
    # Minter addresses are network constants and live in adapters/real/gateway.py.
    gateway_api_url: str = "https://gateway-api-testnet.circle.com/v1"
    # Per-transfer fee ceiling (USDC) used as `maxFee` in the burn intent.
    gateway_max_fee_usdc: float = 2.01

    # ---------- IPFS pin provider -----------------------------------------
    pin_provider: Literal["pinata", "web3storage"] = "pinata"
    pinata_jwt: str = ""
    web3_storage_token: str = ""
    zerog_endpoint: str = ""
    zerog_api_key: str = ""

    # ---------- Persistence -----------------------------------------------
    postgres_dsn: str = "postgresql+asyncpg://akrita:akrita@postgres:5432/akrita"
    postgres_dsn_sync: str = ""  # filled below from postgres_dsn for Alembic
    redis_url: str = "redis://redis:6379/0"

    # ---------- Tunables (NOMOS / pricing) --------------------------------
    pricing_quote_interval: int = 10
    appetite_profile: Literal["conservative", "balanced", "aggressive"] = "balanced"
    subscribed_markets: str = ""  # comma-separated bytes32 market IDs

    # ---------- Tunables (SPATHA / hedge) ---------------------------------
    hedge_check_interval: int = 5
    hedge_inventory_threshold: float = 500.0

    # ---------- Tunables (AGROS / treasury) -------------------------------
    treasury_sweep_interval: int = 60
    safety_multiplier: float = 1.5
    min_usdc_buffer: float = 200.0
    usyc_min_subscribe: float = 50.0
    # Projected next-60min USDC outflow estimate (until derived from open
    # orders/fills). Drives the operational-buffer target.
    treasury_projected_outflow_usdc: float = 200.0
    # Hard per-action cap on any single treasury subscribe/redeem/transfer
    # (USDC). Enforced server-side in the orchestrator — the trust boundary.
    treasury_max_action_usdc: float = 10.0

    # ---------- Safety controls -------------------------------------------
    kill_switch_global: bool = False
    kill_switch_pricing: bool = False
    kill_switch_hedge: bool = False
    kill_switch_treasury: bool = False
    spend_limit_pricing: float = 2500.0
    spend_limit_hedge: float = 5000.0
    spend_limit_treasury: float = 10000.0

    # ---------- LLM provider (NOMOS calibrator) ---------------------------
    llm_provider: str = ""
    llm_api_key: str = ""
    llm_auth_token: str = ""
    llm_base_url: str = ""
    akrita_reasoner_model: str = ""

    # ---------------------------------------------------------------------
    # Structural validators (run at import time)
    # ---------------------------------------------------------------------

    @field_validator(
        "trace_registry_addr",
        "builder_registry_addr",
        "susde_acceptance_addr",
        "claim_registry_addr",
        "pricing_wallet_addr",
        "hedge_wallet_addr",
        "treasury_wallet_addr",
        "trace_wallet_addr",
        "hl_account_addr",
        "hl_api_wallet_addr",
        mode="after",
    )
    @classmethod
    def _validate_eth_address(cls, v: str) -> str:
        if not v:
            return v
        if not ADDR_RE.match(v):
            raise ValueError(f"not a valid 0x-prefixed 20-byte address: {v!r}")
        return v

    @field_validator("poly_builder_code", mode="after")
    @classmethod
    def _validate_builder_code(cls, v: str) -> str:
        if not v:
            return v
        if not BYTES32_RE.match(v):
            raise ValueError("POLY_BUILDER_CODE must be 0x + 64 hex chars when set")
        return v

    @field_validator("circle_api_key", mode="after")
    @classmethod
    def _validate_circle_key(cls, v: str) -> str:
        if not v:
            return v
        if v.count(":") != 2 or not (v.startswith("TEST_API_KEY:") or v.startswith("LIVE_API_KEY:")):
            raise ValueError(
                "CIRCLE_API_KEY must be in TEST_API_KEY:<id>:<secret> "
                "or LIVE_API_KEY:<id>:<secret> form"
            )
        return v

    @field_validator(
        "circle_wallet_set_id",
        "pricing_wallet_id_arc",
        "pricing_wallet_id_matic",
        "hedge_wallet_id_arc",
        "hedge_wallet_id_matic",
        "treasury_wallet_id_arc",
        "treasury_wallet_id_matic",
        "trace_wallet_id_arc",
        "trace_wallet_id_matic",
        mode="after",
    )
    @classmethod
    def _validate_uuid(cls, v: str) -> str:
        if not v:
            return v
        if not re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", v):
            raise ValueError(f"not a valid UUID: {v!r}")
        return v

    @field_validator("postgres_dsn", mode="after")
    @classmethod
    def _normalize_postgres_dsn(cls, v: str) -> str:
        """Ensure the async driver is present so SQLAlchemy picks asyncpg."""
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    # ---------------------------------------------------------------------
    # Derived properties
    # ---------------------------------------------------------------------

    @property
    def subscribed_market_ids(self) -> list[str]:
        return [m.strip() for m in self.subscribed_markets.split(",") if m.strip()]

    @property
    def sync_postgres_dsn(self) -> str:
        """Sync DSN for Alembic (strips +asyncpg)."""
        if self.postgres_dsn_sync:
            return self.postgres_dsn_sync
        return self.postgres_dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


settings = Settings()

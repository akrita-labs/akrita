"""AKRITA orchestrator configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    # Network identifiers
    arc_rpc_url: str = os.environ.get("ARC_RPC_URL", "https://rpc.testnet.arc.io")
    polygon_rpc_url: str = os.environ.get("POLYGON_RPC_URL", "https://polygon-rpc.com")
    hyperliquid_url: str = os.environ.get("HL_URL", "https://api.hyperliquid-testnet.xyz")

    # Contracts on Arc (set at deploy time)
    trace_registry_addr: str = os.environ.get(
        "TRACE_REGISTRY_ADDR", "0x" + "11" * 20,
    )
    builder_registry_addr: str = os.environ.get(
        "BUILDER_REGISTRY_ADDR", "0x" + "22" * 20,
    )

    # Polymarket builder code (bytes32)
    builder_code: str = os.environ.get(
        "POLY_BUILDER_CODE",
        "0x" + "ab" * 32,
    )

    # Polymarket V2 relayer
    polymarket_relayer_url: str = os.environ.get(
        "POLY_RELAYER_URL", "https://clob.polymarket.com",
    )

    # Storage
    postgres_dsn: str = os.environ.get(
        "POSTGRES_DSN",
        "postgresql://akrita:akrita@postgres:5432/akrita",
    )
    redis_url: str = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    # Service ports
    orchestrator_port: int = int(os.environ.get("ORCHESTRATOR_PORT", "8000"))

    # Tunables
    treasury_sweep_interval_sec: int = int(
        os.environ.get("TREASURY_SWEEP_INTERVAL", "60"),
    )
    pricing_quote_interval_sec: int = int(
        os.environ.get("PRICING_QUOTE_INTERVAL", "10"),
    )
    hedge_check_interval_sec: int = int(
        os.environ.get("HEDGE_CHECK_INTERVAL", "5"),
    )

    # Risk thresholds
    hedge_inventory_threshold: float = float(
        os.environ.get("HEDGE_INVENTORY_THRESHOLD", "500.0"),
    )


settings = Settings()

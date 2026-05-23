"""
AKRITA — Depurated parameter surface.

Single source of truth for the *user-facing* tuning knobs each archetype
exposes, plus the internal constants that are NOT user-tunable. The whole
point of this module is depuration: the v1 parameter surface is deliberately
small, and `extra="forbid"` on every params model is the mechanism that
*rejects* removed knobs (gamma, kelly_fraction, inventory_skew_eta,
quote_jitter_ms, ...) instead of silently ignoring them.

The TEMPLATES dict mirrors the 0003 onboarding-seed migration EXACTLY; the two
must stay in lockstep.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Internal constants (NOT user fields)
# ---------------------------------------------------------------------------

GAMMA = 0.1
REQUOTE_COOLDOWN_S = 5
MIN_SPREAD = 0.005
MAX_LOSS_PER_MARKET_PCT = 0.20
SLIPPAGE_BPS = 30
MARGIN_MODE = "cross"
BUILDER_FEE_BPS = 1            # AKRITA fee, disclosure only
PROXY_CORR_MIN = 0.7
MAX_TREASURY_ACTION_USDC = 10.0


def max_funding_bps_hr(a: float) -> float:  # SPATHA coupling
    return min(30.0 * a, 100.0)


# ---------------------------------------------------------------------------
# Per-archetype user-facing parameter models
# ---------------------------------------------------------------------------

class NomosParams(BaseModel):  # 5 user-facing
    quote_spread_bps_offset_to_max_spread: float = Field(0.50, ge=0.10, le=0.90)
    inventory_target_pct: float = Field(0.50, ge=0.0, le=1.0)
    max_position_per_market_usd: float = Field(50, ge=5, le=1000)
    daily_loss_limit_usd: float = Field(20, ge=5, le=10000)
    market_whitelist_tags: list[str] = Field(default_factory=lambda: ["crypto", "sports"])
    model_config = ConfigDict(extra="forbid")   # rejects removed params (gamma, kelly_fraction, inventory_skew_eta, quote_jitter_ms, etc.)


class SpathaParams(BaseModel):  # 4 user-facing
    hedge_band_risk_aversion: float = Field(1.0, ge=0.1, le=10)
    hedge_underlying_whitelist: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    leverage_cap: float = Field(3, ge=1, le=10)
    kill_switch_funding_apr_pct: float = Field(200, ge=50, le=500)
    model_config = ConfigDict(extra="forbid")


class AgrosParams(BaseModel):  # tier selector + tier-gated
    tier: Literal["A", "B", "C"] = "B"
    idle_threshold_usd: float = Field(200, ge=0)
    redemption_buffer_usd: float = Field(200, ge=0)
    sweep_frequency_s: int = Field(60, ge=10)
    safety_buffer_fraction: float = Field(1.5, ge=1.0, le=5.0)
    # tier C only (validated when tier == "C")
    pendle_pt_fraction: float = Field(0.0, ge=0.0, le=1.0)
    susde_fraction: float = Field(0.0, ge=0.0, le=1.0)
    susde_cooldown_acceptance: bool = False   # gate is enforced via on-chain consent elsewhere; this mirrors it
    model_config = ConfigDict(extra="forbid")


ARCHETYPE_PARAMS = {"nomos": NomosParams, "spatha": SpathaParams, "agros": AgrosParams}


def validate_params(archetype: str, raw: dict) -> BaseModel:
    """Return a validated params model for the archetype. Empty dict -> defaults.

    Raises if archetype unknown or removed/unknown keys present (extra=forbid).
    """
    model = ARCHETYPE_PARAMS.get(archetype)
    if model is None:
        raise ValueError(f"unknown archetype {archetype}")
    return model(**(raw or {}))


# ---------------------------------------------------------------------------
# Canonical onboarding templates (mirror the 0003 migration seed EXACTLY)
# ---------------------------------------------------------------------------

TEMPLATES = {
    "conservative_king": {
        "nomos": {
            "quote_spread_bps_offset_to_max_spread": 0.75,
            "inventory_target_pct": 0.5,
            "max_position_per_market_usd": 50,
            "daily_loss_limit_usd": 20,
            "market_whitelist_tags": ["crypto", "sports"],
        },
        "spatha": {
            "hedge_band_risk_aversion": 0.5,
            "hedge_underlying_whitelist": ["BTC", "ETH"],
            "leverage_cap": 2,
            "kill_switch_funding_apr_pct": 200,
        },
        "agros_tier": "A",
        "is_default": False,
    },
    "balanced_counsel": {
        "nomos": {
            "quote_spread_bps_offset_to_max_spread": 0.5,
            "inventory_target_pct": 0.5,
            "max_position_per_market_usd": 50,
            "daily_loss_limit_usd": 20,
            "market_whitelist_tags": ["crypto", "sports"],
        },
        "spatha": {
            "hedge_band_risk_aversion": 1.0,
            "hedge_underlying_whitelist": ["BTC", "ETH", "SOL"],
            "leverage_cap": 3,
            "kill_switch_funding_apr_pct": 200,
        },
        "agros_tier": "B",
        "is_default": True,
    },
    "aggressive_sovereign": {
        "nomos": {
            "quote_spread_bps_offset_to_max_spread": 0.25,
            "inventory_target_pct": 0.5,
            "max_position_per_market_usd": 100,
            "daily_loss_limit_usd": 50,
            "market_whitelist_tags": ["crypto", "sports"],
        },
        "spatha": {
            "hedge_band_risk_aversion": 2.0,
            "hedge_underlying_whitelist": ["BTC", "ETH", "SOL"],
            "leverage_cap": 5,
            "kill_switch_funding_apr_pct": 300,
        },
        "agros_tier": "C",
        "is_default": False,
    },
}

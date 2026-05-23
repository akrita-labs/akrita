"""
AKRITA — Shared data contracts.

Pydantic models for inter-agent communication. These are the strict
JSON schemas that NOMOS, SPATHA, and AGROS produce; the Orchestrator
validates incoming decisions against these.

Every model is versioned in the $schema field so future iterations
can evolve without breaking existing traces.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentRole(str, Enum):
    NOMOS = "nomos"          # Pricing
    SPATHA = "spatha"        # Hedge
    AGROS = "agros"          # Treasury


class AppetiteProfile(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class HedgeVenue(str, Enum):
    HYPERLIQUID = "hyperliquid"
    DYDX_V4 = "dydx_v4"
    ARC_PERP = "arc_perp"      # if/when available
    GMX_V2 = "gmx_v2"


class HedgeSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class MarginAsset(str, Enum):
    USDC = "USDC"
    USYC = "USYC"


class TreasuryAction(str, Enum):
    USYC_SUBSCRIBE = "usyc_subscribe"
    USYC_REDEEM = "usyc_redeem"
    GATEWAY_TRANSFER = "gateway_transfer"
    NOOP = "noop"


class Chain(str, Enum):
    ARC = "arc"                # Arc testnet during hackathon
    POLYGON = "polygon"        # Polymarket V2 settles here
    HYPERLIQUID = "hyperliquid"
    ARBITRUM = "arbitrum"


# ---------------------------------------------------------------------------
# Base decision envelope
# ---------------------------------------------------------------------------

# Owner of pre-multitenant rows; default tenant when a decision omits user_id.
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"


class DecisionBase(BaseModel):
    """Common fields every agent decision carries."""
    model_config = ConfigDict(use_enum_values=True)

    schema_version: str = "akrita/v1"
    decision_id: int = Field(ge=1)
    agent_role: AgentRole
    nonce: int = Field(ge=0, description="Replay-protection nonce")
    ts_ms: int = Field(description="Timestamp in milliseconds since epoch")
    rationale_hash: str = Field(
        pattern=r"^0x[a-f0-9]{64}$",
        description="sha256 of the full reasoning trace body",
    )
    # Multi-tenant identity. Defaults to the system tenant for backward
    # compatibility; user-owned agent instances set both explicitly.
    user_id: str = Field(default=SYSTEM_USER_ID, description="Owning user UUID")
    agent_instance_id: Optional[str] = Field(
        default=None, description="Owning agent_instance UUID"
    )


# ---------------------------------------------------------------------------
# NOMOS — Pricing Agent
# ---------------------------------------------------------------------------

class PricingDecision(DecisionBase):
    """Quote update for a single Polymarket V2 market."""
    agent_role: Literal[AgentRole.NOMOS] = AgentRole.NOMOS

    market_id: str = Field(pattern=r"^0x[a-f0-9]{40,64}$")
    market_question: str = Field(max_length=512)

    # Quoted prices in probability units (0.0 -> 1.0)
    bid: float = Field(ge=0.0, le=1.0)
    ask: float = Field(ge=0.0, le=1.0)
    # Pydantic bound is generous; Risk Agent enforces operational MAX_QUOTE_SIZE_USDC
    size: float = Field(gt=0, le=100_000, description="Order size in shares")
    confidence: float = Field(ge=0.0, le=1.0)

    inventory_limit: float = Field(default=500.0)
    operator_fee_bps: int = Field(default=0, ge=0, le=1000)
    appetite_profile: AppetiteProfile = AppetiteProfile.BALANCED

    # Optional one-line agent-authored narrative for the trace.
    narrative: Optional[str] = None


# ---------------------------------------------------------------------------
# SPATHA — Hedge Agent
# ---------------------------------------------------------------------------

class HedgeDecision(DecisionBase):
    """Open or close a hedge position to neutralize directional exposure."""
    agent_role: Literal[AgentRole.SPATHA] = AgentRole.SPATHA

    market_id: str
    action: Literal["open", "close"]
    venue: HedgeVenue
    instrument: str = Field(description="e.g., 'BTC-PERP', 'ETH-PERP'")
    side: HedgeSide
    size: float = Field(gt=0)
    leverage: float = Field(ge=1.0, le=100.0, default=1.0)
    margin_asset: MarginAsset
    margin_amount: float = Field(gt=0)
    stop_loss: Optional[float] = None

    # If action == "close", reference the original open
    closes_position_id: Optional[int] = None

    # Optional one-line agent-authored narrative for the trace.
    narrative: Optional[str] = None


# ---------------------------------------------------------------------------
# AGROS — Treasury Agent
# ---------------------------------------------------------------------------

class TreasuryDecision(DecisionBase):
    """USYC subscribe/redeem or Gateway cross-chain transfer."""
    agent_role: Literal[AgentRole.AGROS] = AgentRole.AGROS

    action: TreasuryAction
    amount: float = Field(ge=0, description="Amount in USDC or USYC")

    # For Gateway transfers
    src_chain: Optional[Chain] = None
    dst_chain: Optional[Chain] = None

    # Forecasting context (helps trace reconstruction)
    projected_outflow_60min: float = Field(default=0.0)
    safety_multiplier: float = Field(default=1.5)

    # Optional one-line agent-authored narrative for the trace.
    narrative: Optional[str] = None


# ---------------------------------------------------------------------------
# Risk Agent outputs
# ---------------------------------------------------------------------------

class RiskCheckResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class RiskGateResult(BaseModel):
    approved: bool
    checks: list[RiskCheckResult]
    reason: str = ""


# ---------------------------------------------------------------------------
# Trace bodies (the audit-trail content)
# ---------------------------------------------------------------------------

class TraceBody(BaseModel):
    """The full reasoning trace pinned to IPFS and hashed for on-chain anchor."""
    schema_version: str = "akrita/trace/v1"
    decision_id: int
    agent_role: AgentRole
    decision_type: str
    user_id: str = SYSTEM_USER_ID
    agent_instance_id: Optional[str] = None

    # Trading-R1 inspired structure
    fundamentals: dict
    technical: dict
    conclusion: dict

    # Optional one-line human-readable narrative. Defaults None so trace
    # canonicalization is unchanged when absent — agents may author it, and the
    # decisions router also mirrors it into conclusion["narrative"].
    narrative: Optional[str] = None

    # Risk-gate verdict
    risk_gate: RiskGateResult

    # Metadata
    model: str = "unset"
    computation_ms: int = 0
    ts_ms: int


# ---------------------------------------------------------------------------
# State snapshots (read endpoints)
# ---------------------------------------------------------------------------

class InventorySnapshot(BaseModel):
    market_id: str
    net_exposure: float
    long_size: float
    short_size: float
    snapshot_ts_ms: int


class BalanceSnapshot(BaseModel):
    wallet: str
    chain: Chain
    usdc: float
    usyc: float
    pusd: float = 0.0
    ts_ms: int


# ---------------------------------------------------------------------------
# Union type for any decision (used in deserialization)
# ---------------------------------------------------------------------------

AnyDecision = Union[PricingDecision, HedgeDecision, TreasuryDecision]

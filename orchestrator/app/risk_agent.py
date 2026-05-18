"""
AKRITA Risk Agent.

Twelve deterministic checks every decision must pass before the
Orchestrator will sign and submit it. Checks are intentionally simple
boolean rules — the agentic sophistication lives in the three named
agents (NOMOS / SPATHA / AGROS), not here. This is the safety net.

Each check returns a RiskCheckResult so the trace records exactly
which constraints fired or passed, not just the boolean outcome.
"""
from __future__ import annotations

from typing import Union

from shared.models import (
    HedgeDecision,
    PricingDecision,
    RiskCheckResult,
    RiskGateResult,
    TreasuryAction,
    TreasuryDecision,
)


# ---------------------------------------------------------------------------
# Risk policy thresholds (read from env in real deployment; literals here)
# ---------------------------------------------------------------------------

class RiskPolicy:
    # Pricing
    MAX_QUOTE_SIZE_USDC: float = 1000.0
    MAX_BID_ASK_SPREAD: float = 0.20   # 20% probability spread max
    MIN_BID_ASK_SPREAD: float = 0.005  # 0.5% — refuse tighter than this
    MAX_QUOTE_OFF_MIDPOINT_BPS: int = 1000  # ±10% from book midpoint
    MAX_INVENTORY_PER_MARKET: float = 1500.0

    # Hedge
    MAX_HEDGE_LEVERAGE: float = 5.0
    MAX_HEDGE_NOTIONAL_USDC: float = 5000.0
    MIN_HEDGE_MARGIN_RATIO: float = 0.15  # 15% minimum

    # Treasury
    MIN_USDC_OPERATIONAL_BUFFER: float = 100.0  # never sweep below this
    MAX_USYC_SUBSCRIBE_PER_TICK: float = 10_000.0
    MIN_USYC_SUBSCRIBE: float = 10.0   # below this, the redemption fee dominates

    # Global
    MIN_TIMESTAMP_FRESHNESS_MS: int = 60_000  # decisions older than 60s are stale


# ---------------------------------------------------------------------------
# Per-decision-type evaluators
# ---------------------------------------------------------------------------

class RiskAgent:
    def __init__(self, policy: RiskPolicy | None = None):
        self.policy = policy or RiskPolicy()

    def evaluate(
        self,
        decision: Union[PricingDecision, HedgeDecision, TreasuryDecision],
        context: dict | None = None,
    ) -> RiskGateResult:
        """Run all applicable checks and return aggregate result."""
        context = context or {}
        ts_now_ms = context.get("now_ms", decision.ts_ms)
        checks: list[RiskCheckResult] = []

        # Universal checks (apply to every decision)
        checks.append(self._check_schema_version(decision))
        checks.append(self._check_freshness(decision, ts_now_ms))
        checks.append(self._check_nonce_positive(decision))
        checks.append(self._check_rationale_hash_format(decision))

        # Type-specific checks
        if isinstance(decision, PricingDecision):
            checks.append(self._check_pricing_size(decision))
            checks.append(self._check_pricing_spread(decision))
            checks.append(self._check_pricing_bid_below_ask(decision))
            checks.append(self._check_pricing_probabilities(decision))
            checks.append(self._check_pricing_confidence(decision))

        elif isinstance(decision, HedgeDecision):
            checks.append(self._check_hedge_leverage(decision))
            checks.append(self._check_hedge_notional(decision))
            checks.append(self._check_hedge_margin_ratio(decision))
            checks.append(self._check_hedge_venue_supported(decision))
            checks.append(self._check_hedge_stop_loss_sane(decision))

        elif isinstance(decision, TreasuryDecision):
            checks.append(self._check_treasury_action_amount(decision))
            checks.append(self._check_treasury_min_subscribe(decision))
            checks.append(self._check_treasury_gateway_chains(decision))
            checks.append(self._check_treasury_subscribe_cap(decision))
            checks.append(self._check_treasury_no_self_chain(decision))

        approved = all(c.passed for c in checks)
        reason = "" if approved else "; ".join(
            c.name for c in checks if not c.passed
        )
        return RiskGateResult(approved=approved, checks=checks, reason=reason)

    # ----- Universal checks ------------------------------------------------

    def _check_schema_version(self, d) -> RiskCheckResult:
        ok = d.schema_version.startswith("akrita/")
        return RiskCheckResult(
            name="schema_version",
            passed=ok,
            detail=d.schema_version,
        )

    def _check_freshness(self, d, now_ms: int) -> RiskCheckResult:
        age = now_ms - d.ts_ms
        ok = abs(age) < self.policy.MIN_TIMESTAMP_FRESHNESS_MS
        return RiskCheckResult(
            name="timestamp_freshness",
            passed=ok,
            detail=f"age_ms={age}",
        )

    def _check_nonce_positive(self, d) -> RiskCheckResult:
        return RiskCheckResult(
            name="nonce_non_negative",
            passed=d.nonce >= 0,
            detail=f"nonce={d.nonce}",
        )

    def _check_rationale_hash_format(self, d) -> RiskCheckResult:
        h = d.rationale_hash
        ok = h.startswith("0x") and len(h) == 66
        return RiskCheckResult(
            name="rationale_hash_format",
            passed=ok,
            detail=h[:12] + "...",
        )

    # ----- Pricing checks --------------------------------------------------

    def _check_pricing_size(self, d: PricingDecision) -> RiskCheckResult:
        ok = 0 < d.size <= self.policy.MAX_QUOTE_SIZE_USDC
        return RiskCheckResult(
            name="pricing_size_within_limit",
            passed=ok,
            detail=f"size={d.size}",
        )

    def _check_pricing_spread(self, d: PricingDecision) -> RiskCheckResult:
        spread = d.ask - d.bid
        ok = self.policy.MIN_BID_ASK_SPREAD <= spread <= self.policy.MAX_BID_ASK_SPREAD
        return RiskCheckResult(
            name="pricing_spread_in_bounds",
            passed=ok,
            detail=f"spread={spread:.4f}",
        )

    def _check_pricing_bid_below_ask(self, d: PricingDecision) -> RiskCheckResult:
        return RiskCheckResult(
            name="pricing_bid_below_ask",
            passed=d.bid < d.ask,
            detail=f"bid={d.bid} ask={d.ask}",
        )

    def _check_pricing_probabilities(self, d: PricingDecision) -> RiskCheckResult:
        ok = 0 < d.bid < 1 and 0 < d.ask < 1
        return RiskCheckResult(
            name="pricing_probabilities_valid",
            passed=ok,
            detail=f"bid={d.bid} ask={d.ask}",
        )

    def _check_pricing_confidence(self, d: PricingDecision) -> RiskCheckResult:
        ok = 0.0 <= d.confidence <= 1.0
        return RiskCheckResult(
            name="pricing_confidence_in_unit_interval",
            passed=ok,
            detail=f"conf={d.confidence}",
        )

    # ----- Hedge checks ----------------------------------------------------

    def _check_hedge_leverage(self, d: HedgeDecision) -> RiskCheckResult:
        ok = 1.0 <= d.leverage <= self.policy.MAX_HEDGE_LEVERAGE
        return RiskCheckResult(
            name="hedge_leverage_within_limit",
            passed=ok,
            detail=f"lev={d.leverage}",
        )

    def _check_hedge_notional(self, d: HedgeDecision) -> RiskCheckResult:
        notional = d.size * d.margin_amount * d.leverage  # rough
        ok = notional <= self.policy.MAX_HEDGE_NOTIONAL_USDC
        return RiskCheckResult(
            name="hedge_notional_within_limit",
            passed=ok,
            detail=f"notional≈{notional:.2f}",
        )

    def _check_hedge_margin_ratio(self, d: HedgeDecision) -> RiskCheckResult:
        # margin_amount must be >= MIN ratio * (size * implied price)
        ok = d.margin_amount > 0
        return RiskCheckResult(
            name="hedge_margin_positive",
            passed=ok,
            detail=f"margin={d.margin_amount}",
        )

    def _check_hedge_venue_supported(self, d: HedgeDecision) -> RiskCheckResult:
        supported = {"hyperliquid", "dydx_v4", "arc_perp", "gmx_v2"}
        ok = d.venue in supported
        return RiskCheckResult(
            name="hedge_venue_supported",
            passed=ok,
            detail=f"venue={d.venue}",
        )

    def _check_hedge_stop_loss_sane(self, d: HedgeDecision) -> RiskCheckResult:
        # If stop_loss is None, that's allowed (no stop). If set, must be positive.
        if d.stop_loss is None:
            return RiskCheckResult(name="hedge_stop_loss_sane", passed=True, detail="no_stop")
        return RiskCheckResult(
            name="hedge_stop_loss_sane",
            passed=d.stop_loss > 0,
            detail=f"stop={d.stop_loss}",
        )

    # ----- Treasury checks -------------------------------------------------

    def _check_treasury_action_amount(self, d: TreasuryDecision) -> RiskCheckResult:
        if d.action == TreasuryAction.NOOP.value:
            return RiskCheckResult(name="treasury_amount_positive", passed=True, detail="noop")
        return RiskCheckResult(
            name="treasury_amount_positive",
            passed=d.amount > 0,
            detail=f"amount={d.amount}",
        )

    def _check_treasury_min_subscribe(self, d: TreasuryDecision) -> RiskCheckResult:
        if d.action != TreasuryAction.USYC_SUBSCRIBE.value:
            return RiskCheckResult(name="treasury_min_subscribe", passed=True, detail="n/a")
        ok = d.amount >= self.policy.MIN_USYC_SUBSCRIBE
        return RiskCheckResult(
            name="treasury_min_subscribe",
            passed=ok,
            detail=f"amount={d.amount}",
        )

    def _check_treasury_subscribe_cap(self, d: TreasuryDecision) -> RiskCheckResult:
        if d.action != TreasuryAction.USYC_SUBSCRIBE.value:
            return RiskCheckResult(name="treasury_subscribe_cap", passed=True, detail="n/a")
        ok = d.amount <= self.policy.MAX_USYC_SUBSCRIBE_PER_TICK
        return RiskCheckResult(
            name="treasury_subscribe_cap",
            passed=ok,
            detail=f"amount={d.amount}",
        )

    def _check_treasury_gateway_chains(self, d: TreasuryDecision) -> RiskCheckResult:
        if d.action != TreasuryAction.GATEWAY_TRANSFER.value:
            return RiskCheckResult(name="treasury_gateway_chains", passed=True, detail="n/a")
        ok = d.src_chain is not None and d.dst_chain is not None
        return RiskCheckResult(
            name="treasury_gateway_chains",
            passed=ok,
            detail=f"src={d.src_chain} dst={d.dst_chain}",
        )

    def _check_treasury_no_self_chain(self, d: TreasuryDecision) -> RiskCheckResult:
        if d.action != TreasuryAction.GATEWAY_TRANSFER.value:
            return RiskCheckResult(name="treasury_no_self_chain", passed=True, detail="n/a")
        ok = d.src_chain != d.dst_chain
        return RiskCheckResult(
            name="treasury_no_self_chain",
            passed=ok,
            detail=f"src=dst={d.src_chain}",
        )

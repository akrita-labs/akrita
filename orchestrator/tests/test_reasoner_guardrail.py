"""
Guardrail + sizing unit tests for the agentic decision layer.

These cover the pure, safety-critical logic that bounds the agents — no network,
no model calls. They lock in two invariants:
  - NOMOS: the model may extend the deterministic rules upward (issue beyond the
    rules only at high conviction) but can never silently override the safe default.
  - SPATHA: stake size is confidence/severity scaled and hard-capped, and falls to
    zero below the conviction floor.
"""
from agents.nomos.reasoner import (
    ISSUE_BEYOND_RULES_CONFIDENCE,
    apply_rules_floor,
)
from agents.spatha.bond_conviction import (
    MIN_CONVICTION_TO_STAKE,
    conviction_plan,
    size_stake,
)


def test_floor_issues_when_rules_flagged_and_model_agrees():
    risk = {"flagged": True, "reasons": ["honeypot (cannot sell)"]}
    assert apply_rules_floor({"decision": "issue", "confidence": 0.4}, risk) is True


def test_floor_blocks_when_model_skips_even_if_rules_flagged():
    risk = {"flagged": True, "reasons": ["honeypot (cannot sell)"]}
    assert apply_rules_floor({"decision": "skip", "confidence": 0.9}, risk) is False


def test_floor_blocks_low_confidence_issue_beyond_rules():
    # Rules did NOT flag (e.g. only context flags like USDT) -> issuing requires
    # high conviction; a lukewarm model call must not flag a blue-chip token.
    risk = {"flagged": False, "reasons": []}
    low = {"decision": "issue", "confidence": ISSUE_BEYOND_RULES_CONFIDENCE - 0.1}
    assert apply_rules_floor(low, risk) is False


def test_floor_allows_high_conviction_issue_beyond_rules():
    risk = {"flagged": False, "reasons": []}
    high = {"decision": "issue", "confidence": ISSUE_BEYOND_RULES_CONFIDENCE + 0.05}
    assert apply_rules_floor(high, risk) is True


def test_size_stake_zero_below_floor():
    assert size_stake(MIN_CONVICTION_TO_STAKE - 0.01, "critical", max_stake_usdc=10) == 0.0


def test_size_stake_scales_and_caps():
    full = size_stake(1.0, "critical", max_stake_usdc=10)
    assert full == 10.0  # conviction 1.0 * critical weight 1.0 * cap
    partial = size_stake(0.8, "medium", max_stake_usdc=10)
    assert 0.0 < partial < full


def test_conviction_plan_abstain_is_no_action():
    plan = conviction_plan({"severity": "high"}, {"position": "abstain"}, max_stake_usdc=10)
    assert plan["action"] == "none" and plan["amount_usdc"] == 0.0


def test_conviction_plan_back_stakes_for_side():
    plan = conviction_plan(
        {"severity": "critical"},
        {"position": "back", "conviction": 0.9},
        max_stake_usdc=10,
    )
    assert plan["action"] == "stake"
    assert plan["backs_claim"] is True
    assert plan["amount_base_units"] == int(round(plan["amount_usdc"] * 1_000_000))

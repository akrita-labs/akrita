"""Hermetic tests for the AKRITA v1 onboarding router + reputation aggregation.

No DB, no network: `state` is replaced with an AsyncMock so the route handlers
exercise their gate/persistence logic against in-memory fakes. The pure
`instance_gate_check` and the reputation scoring functions are tested directly.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from orchestrator.app.reputation import (
    SCORE_BASELINE,
    SCORE_MAX,
    compute_reputation_summary,
    push_reputation,
    score_from_components,
)
from orchestrator.app.routers import onboarding
from orchestrator.app.routers.onboarding import instance_gate_check


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeRequest:
    """Minimal stand-in for fastapi.Request exposing only `.client.host`."""

    class _Client:
        host = "203.0.113.7"

    client = _Client()


def _state_with_user(**overrides):
    """An AsyncMock `state` with a present user and empty everything else."""
    state = AsyncMock()
    state.get_user.return_value = {"id": "u1", "handle": "alice", "msca_address": None}
    state.get_consent.return_value = None
    state.has_consent.return_value = False
    state.feedback_by_user.return_value = {}
    state.volume_by_user.return_value = {}
    state.trace_count_by_user.return_value = {}
    state.get_builder_profile.return_value = None
    state.list_user_instances.return_value = []
    state.list_feedback.return_value = []
    state.record_consent.return_value = {"id": 1}
    for k, v in overrides.items():
        getattr(state, k).return_value = v
    return state


# ---------------------------------------------------------------------------
# Jurisdiction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jurisdiction_us_person_true(monkeypatch):
    state = _state_with_user()
    monkeypatch.setattr("orchestrator.app.state.state", state, raising=False)

    body = onboarding.JurisdictionBody(user_id="u1", jurisdiction_declared="US")
    out = await onboarding.declare_jurisdiction(body, _FakeRequest())

    assert out["jurisdiction_declared"] == "US"
    assert out["ip_country"] == "US"
    assert out["is_us_person"] is True
    # Persisted via the consent write path (no users.jurisdiction setter in v1).
    state.record_consent.assert_awaited_once()
    kwargs = state.record_consent.await_args.kwargs
    assert kwargs["consent_type"] == "jurisdiction"
    assert kwargs["typed_data"]["is_us_person"] is True


@pytest.mark.asyncio
async def test_jurisdiction_gb_person_not_us(monkeypatch):
    state = _state_with_user()
    monkeypatch.setattr("orchestrator.app.state.state", state, raising=False)

    body = onboarding.JurisdictionBody(user_id="u1", jurisdiction_declared="GB")
    out = await onboarding.declare_jurisdiction(body, _FakeRequest())

    assert out["jurisdiction_declared"] == "GB"
    assert out["ip_country"] == "GB"
    assert out["is_us_person"] is False


@pytest.mark.asyncio
async def test_jurisdiction_lowercase_normalised(monkeypatch):
    state = _state_with_user()
    monkeypatch.setattr("orchestrator.app.state.state", state, raising=False)

    body = onboarding.JurisdictionBody(user_id="u1", jurisdiction_declared="gb")
    out = await onboarding.declare_jurisdiction(body, _FakeRequest())
    assert out["jurisdiction_declared"] == "GB"
    assert out["is_us_person"] is False


# ---------------------------------------------------------------------------
# Gate logic (pure function)
# ---------------------------------------------------------------------------

def test_gate_agros_tier_a_us_person_blocked():
    allowed, code, msg = instance_gate_check(
        "agros", "A", is_us_person=True, has_susde_consent=False, has_jurisdiction=True
    )
    assert allowed is False
    assert code == 403
    assert "US" in msg


def test_gate_agros_tier_c_without_consent_blocked():
    allowed, code, msg = instance_gate_check(
        "agros", "C", is_us_person=False, has_susde_consent=False, has_jurisdiction=True
    )
    assert allowed is False
    assert code == 409
    assert "consent" in msg.lower()


def test_gate_agros_tier_c_with_consent_allowed():
    allowed, code, _ = instance_gate_check(
        "agros", "C", is_us_person=False, has_susde_consent=True, has_jurisdiction=True
    )
    assert allowed is True
    assert code == 200


def test_gate_agros_tier_a_non_us_with_jurisdiction_allowed():
    allowed, code, _ = instance_gate_check(
        "agros", "A", is_us_person=False, has_susde_consent=False, has_jurisdiction=True
    )
    assert allowed is True
    assert code == 200


def test_gate_agros_no_jurisdiction_blocked():
    allowed, code, _ = instance_gate_check(
        "agros", "B", is_us_person=False, has_susde_consent=False, has_jurisdiction=False
    )
    assert allowed is False
    assert code == 409


def test_gate_nomos_always_allowed():
    # NOMOS is ungated even with no jurisdiction and a US person.
    allowed, code, _ = instance_gate_check(
        "nomos", None, is_us_person=True, has_susde_consent=False, has_jurisdiction=False
    )
    assert allowed is True
    assert code == 200


def test_gate_spatha_always_allowed():
    allowed, code, _ = instance_gate_check(
        "spatha", None, is_us_person=True, has_susde_consent=False, has_jurisdiction=False
    )
    assert allowed is True
    assert code == 200


# ---------------------------------------------------------------------------
# Reputation scoring
# ---------------------------------------------------------------------------

def test_score_baseline_with_no_components():
    assert score_from_components({}) == SCORE_BASELINE


def test_score_monotonic_in_volume():
    s0 = score_from_components({"maker_volume": 0.0})
    s1 = score_from_components({"maker_volume": 1_000.0})
    s2 = score_from_components({"maker_volume": 10_000.0})
    assert s0 < s1 < s2  # strictly increasing in attributed maker volume
    assert s0 == SCORE_BASELINE


def test_score_clamped_to_uint64_range():
    huge = score_from_components({"maker_volume": 10**12, "yield_accrued": 10**9})
    assert 0 <= huge <= SCORE_MAX
    assert huge == SCORE_MAX


def test_score_never_negative():
    s = score_from_components({"hedge_pnl": -10**9})
    assert s == 0


# ---------------------------------------------------------------------------
# Reputation summary shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_reputation_summary_shape():
    state = AsyncMock()
    state.feedback_by_user.return_value = {
        "u1": {
            "total_delta": 12.5,
            "count": 3,
            "by_type": {
                "brier_resolved": {"total_delta": 0.4, "count": 2},
                "hedge_pnl": {"total_delta": 5.0, "count": 1},
            },
        }
    }
    state.volume_by_user.return_value = {"u1": {"volume": 500.0, "fees": 1.0, "fills": 4}}
    state.trace_count_by_user.return_value = {"u1": 7}
    state.get_builder_profile.return_value = {"onchain_agent_id": 101}

    summary = await compute_reputation_summary("u1", state=state)

    assert summary["user_id"] == "u1"
    assert summary["erc8004_id"] == 101
    assert summary["total_delta"] == 12.5
    assert summary["attributed_volume_usdc"] == 500.0
    assert summary["trace_count"] == 7
    assert set(summary["components"]) == {
        "maker_volume", "brier_resolved", "hedge_pnl", "yield_accrued"
    }
    assert summary["components"]["maker_volume"] == 500.0
    assert summary["components"]["brier_resolved"] == 0.4
    # Score reflects the components and stays in range.
    assert 0 <= summary["score"] <= SCORE_MAX
    assert summary["score"] > SCORE_BASELINE  # positive volume + brier + pnl


@pytest.mark.asyncio
async def test_compute_reputation_summary_empty_user():
    state = AsyncMock()
    state.feedback_by_user.return_value = {}
    state.volume_by_user.return_value = {}
    state.trace_count_by_user.return_value = {}
    state.get_builder_profile.return_value = None

    summary = await compute_reputation_summary("ghost", state=state)
    assert summary["erc8004_id"] is None
    assert summary["score"] == SCORE_BASELINE
    assert summary["attributed_volume_usdc"] == 0.0
    assert summary["trace_count"] == 0


# ---------------------------------------------------------------------------
# push_reputation defaults to dry-run / held
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_reputation_defaults_to_dry_run_held():
    state = AsyncMock()
    state.feedback_by_user.return_value = {
        "u1": {"total_delta": 1.0, "count": 1, "by_type": {}}
    }
    state.volume_by_user.return_value = {"u1": {"volume": 100.0}}
    state.trace_count_by_user.return_value = {"u1": 1}
    state.get_builder_profile.return_value = {"onchain_agent_id": 5}
    state.list_feedback.return_value = [{"id": 1, "onchain_tx": None}, {"id": 2, "onchain_tx": "0xabc"}]

    adapters = AsyncMock()  # has no update_reputation capability that matters in dry-run
    out = await push_reputation("u1", adapters=adapters, state=state)

    assert out["broadcast"] is False
    assert out["held"] is True
    assert out["dry_run"] is True
    assert out["planned_call"]["method"] == "updateReputation"
    assert out["planned_call"]["args"]["agentId"] == 5
    assert out["unpushed_feedback_ids"] == [1]  # only the un-pushed row
    state.mark_feedback_pushed.assert_not_awaited()


@pytest.mark.asyncio
async def test_push_reputation_held_when_no_oracle_capability():
    state = AsyncMock()
    state.feedback_by_user.return_value = {"u1": {"total_delta": 0.0, "count": 0, "by_type": {}}}
    state.volume_by_user.return_value = {}
    state.trace_count_by_user.return_value = {}
    state.get_builder_profile.return_value = {"onchain_agent_id": 5}
    state.list_feedback.return_value = []

    # An adapters container with arc/builder that do NOT expose update_reputation.
    class _Bare:
        pass

    class _Adapters:
        arc = _Bare()
        builder = _Bare()

    out = await push_reputation("u1", adapters=_Adapters(), state=state, dry_run=False)
    assert out["broadcast"] is False
    assert out["held"] is True
    assert "reputation-oracle" in out["note"]
    state.mark_feedback_pushed.assert_not_awaited()


@pytest.mark.asyncio
async def test_push_reputation_broadcasts_with_oracle_capability():
    state = AsyncMock()
    state.feedback_by_user.return_value = {"u1": {"total_delta": 0.0, "count": 0, "by_type": {}}}
    state.volume_by_user.return_value = {"u1": {"volume": 200.0}}
    state.trace_count_by_user.return_value = {}
    state.get_builder_profile.return_value = {"onchain_agent_id": 9}
    state.list_feedback.return_value = [{"id": 11, "onchain_tx": None}]

    class _Receipt:
        tx_hash = "0xdeadbeef"

    class _Arc:
        async def update_reputation(self, agent_id, score):
            assert agent_id == 9
            assert isinstance(score, int)
            return _Receipt()

    class _Adapters:
        arc = _Arc()
        builder = None

    out = await push_reputation("u1", adapters=_Adapters(), state=state, dry_run=False)
    assert out["broadcast"] is True
    assert out["held"] is False
    assert out["tx_hash"] == "0xdeadbeef"
    state.mark_feedback_pushed.assert_awaited_once_with([11], "0xdeadbeef")

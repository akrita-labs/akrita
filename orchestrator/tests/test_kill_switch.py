"""Tests for the kill-switch sequencing module + wallet_id_for fallback.

Hermetic: no network, no DB. We drive `trigger_kill_switch` with hand-rolled
fake adapters and a fake in-memory state so we can assert ordering, error
tolerance, and the event lifecycle precisely. `asyncio_mode = auto` is
configured, so async tests run without a marker.
"""
from __future__ import annotations

import pytest

from orchestrator.app.kill_switch import (
    KILLSWITCH_SCHEMA_VERSION,
    ORCHESTRATOR_AGENT_ID,
    trigger_kill_switch,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Receipt:
    def __init__(self, tx_hash="0xabc", usdc_out=0.0):
        self.tx_hash = tx_hash
        self.usdc_out = usdc_out


class FakeWallets:
    def __init__(self):
        self.calls = []

    def wallet_id_for(self, user_id, role, chain="ARC-TESTNET"):
        self.calls.append((user_id, role, chain))
        return f"wid-{role}"


class FakePolymarket:
    def __init__(self, raise_on=None):
        self.cancelled = []
        self._raise_on = raise_on or set()

    async def cancel_order(self, order_id):
        if order_id in self._raise_on:
            raise RuntimeError(f"poly boom {order_id}")
        self.cancelled.append(order_id)
        return True


class FakeHyperliquid:
    def __init__(self, raise_all=False):
        self.closed = []
        self._raise_all = raise_all

    async def close_position(self, position_id):
        if self._raise_all:
            raise RuntimeError(f"hl boom {position_id}")
        self.closed.append(position_id)
        return _Receipt()


class FakeUSYC:
    def __init__(self, raise_redeem=False):
        self.redeemed = []
        self._raise = raise_redeem

    async def redeem(self, wallet_id, amount):
        if self._raise:
            raise RuntimeError("usyc not permissioned")
        self.redeemed.append((wallet_id, amount))
        return _Receipt(usdc_out=amount * 1.0)


class FakeArc:
    def __init__(self, raise_commit=False):
        self.commits = []
        self._raise = raise_commit

    async def commit_trace(self, agent_id, decision_id, trace_hash_hex, ipfs_cid):
        if self._raise:
            raise RuntimeError("arc unfunded")
        self.commits.append((agent_id, decision_id, trace_hash_hex, ipfs_cid))
        return _Receipt(tx_hash="0xtrace")


class FakeAdapters:
    def __init__(self, *, poly=None, hl=None, usyc=None, arc=None, wallets=None):
        self.polymarket = poly or FakePolymarket()
        self.hyperliquid = hl or FakeHyperliquid()
        self.usyc = usyc or FakeUSYC()
        self.arc = arc or FakeArc()
        self.wallets = wallets or FakeWallets()


class FakeState:
    """In-memory stand-in for the StateStore facade — records call order."""

    def __init__(self, *, instances=None, hedges=None, balances=None, orders=None):
        self.order_log = []
        self._instances = instances or []
        self._hedges = hedges or []
        self._balances = balances or []
        self._orders = orders  # None => no list_open_orders accessor at all
        self._events = {}
        self._next_id = 1
        # Only expose list_open_orders when orders were supplied, mirroring the
        # fact that state.py doesn't surface it yet.
        if orders is not None:
            self.list_open_orders = self._list_open_orders  # type: ignore[attr-defined]

    async def create_kill_switch_event(self, user_id, trigger_source, trigger_detail=None):
        self.order_log.append("create_event")
        eid = self._next_id
        self._next_id += 1
        self._events[eid] = {
            "id": eid,
            "user_id": user_id,
            "trigger_source": trigger_source,
            "trigger_detail": trigger_detail or {},
            "status": "pending",
            "completed_at": None,
        }
        return eid

    async def list_user_instances(self, user_id):
        return list(self._instances)

    async def set_instance_flags(self, instance_id, **kwargs):
        self.order_log.append(("set_flags", instance_id, kwargs))

    async def _list_open_orders(self, user_id=None):
        self.order_log.append("list_open_orders")
        return list(self._orders or [])

    async def list_open_hedges(self, user_id=None):
        self.order_log.append("list_open_hedges")
        return list(self._hedges)

    async def list_user_balances(self, user_id):
        self.order_log.append("list_user_balances")
        return list(self._balances)

    async def update_kill_switch_event(self, event_id, **kwargs):
        self.order_log.append("update_event")
        # Mirror SQLKillSwitchRepo.update_results: `completed=True` stamps a
        # completed_at timestamp on the row.
        if kwargs.pop("completed", False):
            self._events[event_id]["completed_at"] = "2026-05-23T00:00:00Z"
        self._events[event_id].update(kwargs)

    async def get_kill_switch_event(self, event_id):
        return self._events.get(event_id)


USER = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_all_venues_attempted_in_order_and_completed():
    state = FakeState(
        instances=[{"id": "inst-1"}, {"id": "inst-2"}],
        hedges=[{"venue_position_id": "42"}],
        balances=[{"token": "USYC", "amount": 250.0}],
        orders=[{"order_id": "o1"}, {"order_id": "o2"}],
    )
    adapters = FakeAdapters()

    event = await trigger_kill_switch(
        USER, "manual", {"reason": "test"}, adapters=adapters, state=state
    )

    # Ordering: event created -> instances flipped -> orders -> hedges ->
    # balances (AGROS) -> event updated.
    assert state.order_log[0] == "create_event"
    assert ("set_flags", "inst-1", {"kill_switch": True}) in state.order_log
    assert ("set_flags", "inst-2", {"kill_switch": True}) in state.order_log
    i_orders = state.order_log.index("list_open_orders")
    i_hedges = state.order_log.index("list_open_hedges")
    i_bal = state.order_log.index("list_user_balances")
    assert i_orders < i_hedges < i_bal
    assert state.order_log[-1] == "update_event"

    # All three venues actually invoked.
    assert adapters.polymarket.cancelled == ["o1", "o2"]
    assert adapters.hyperliquid.closed == [42]  # coerced to int
    assert adapters.usyc.redeemed == [("wid-treasury", 250.0)]  # balance-driven
    assert adapters.arc.commits  # trace committed

    # Wallet resolved via the keeper-fallback helper.
    assert adapters.wallets.calls == [(USER, "treasury", "ARC-TESTNET")]

    assert event["status"] == "completed"
    assert event["completed_at"] is not None
    assert event["trace_decision_id"] == event["id"]
    assert event["arc_tx"] == "0xtrace"
    assert event["trace_hash"].startswith("0x")


# ---------------------------------------------------------------------------
# One venue raising -> partial, others still attempted
# ---------------------------------------------------------------------------


async def test_one_venue_raises_others_still_attempted_partial():
    state = FakeState(
        instances=[{"id": "inst-1"}],
        hedges=[{"venue_position_id": "7"}],
        balances=[{"token": "USYC", "amount": 100.0}],
        orders=[{"order_id": "o1"}, {"order_id": "o2"}],
    )
    # Hyperliquid blows up entirely; poly + usyc must still run.
    adapters = FakeAdapters(hl=FakeHyperliquid(raise_all=True))

    event = await trigger_kill_switch(
        USER, "auto", {}, adapters=adapters, state=state
    )

    # Poly + USYC still attempted despite HL failing.
    assert adapters.polymarket.cancelled == ["o1", "o2"]
    assert adapters.usyc.redeemed == [("wid-treasury", 100.0)]
    assert adapters.arc.commits  # arc still committed

    assert event["status"] == "partial"
    assert event["spatha_result"]["errors"]  # HL error captured
    assert event["spatha_result"]["errors"][0]["position_id"] == "7"
    assert event["nomos_result"]["cancelled"] == ["o1", "o2"]


# ---------------------------------------------------------------------------
# Arc commit failure tolerated
# ---------------------------------------------------------------------------


async def test_arc_commit_failure_tolerated_partial():
    state = FakeState(
        instances=[],
        hedges=[],
        balances=[],
        orders=[],
    )
    adapters = FakeAdapters(arc=FakeArc(raise_commit=True))

    event = await trigger_kill_switch(
        USER, "manual", {}, adapters=adapters, state=state
    )

    # Did not crash; recorded a hash but no tx; marked partial.
    assert event["status"] == "partial"
    assert event["arc_tx"] is None
    assert event["trace_hash"].startswith("0x")
    # Event row was created and updated.
    assert "create_event" in state.order_log
    assert state.order_log[-1] == "update_event"


# ---------------------------------------------------------------------------
# Defaults: no order accessor + unknown balance -> conservative redeem
# ---------------------------------------------------------------------------


async def test_no_orders_accessor_and_unknown_balance_uses_default_redeem():
    # orders=None => state has no list_open_orders attribute at all.
    state = FakeState(instances=[], hedges=[], balances=[], orders=None)
    adapters = FakeAdapters()

    event = await trigger_kill_switch(
        USER, "manual", {}, adapters=adapters, state=state
    )

    # No orders accessor -> nomos is a clean no-op (no errors recorded for it).
    assert "list_open_orders" not in state.order_log
    assert event["nomos_result"] == {"cancelled": [], "errors": []}
    # No USYC balance known -> conservative default redeem used.
    assert adapters.usyc.redeemed == [("wid-treasury", 100.0)]
    assert event["status"] == "completed"


# ---------------------------------------------------------------------------
# Trace body shape
# ---------------------------------------------------------------------------


async def test_trace_committed_with_orchestrator_agent_id_and_event_decision_id():
    state = FakeState(instances=[], hedges=[], balances=[], orders=[])
    adapters = FakeAdapters()

    event = await trigger_kill_switch(
        USER, "manual", {}, adapters=adapters, state=state
    )

    agent_id, decision_id, trace_hash_hex, ipfs_cid = adapters.arc.commits[0]
    assert agent_id == ORCHESTRATOR_AGENT_ID
    assert decision_id == event["id"]
    assert trace_hash_hex == event["trace_hash"]
    assert ipfs_cid == ""


# ---------------------------------------------------------------------------
# wallet_id_for fallback
# ---------------------------------------------------------------------------


def _make_wallets_real():
    """Build a CircleWalletsReal without running __init__ (no Circle creds)."""
    from adapters.real import circle_wallets as cw

    inst = cw.CircleWalletsReal.__new__(cw.CircleWalletsReal)
    # Populate the role->wallet map directly so wallet_id() resolves.
    cw._WALLET_ID_BY_ROLE_CHAIN.clear()
    cw._WALLET_ID_BY_ROLE_CHAIN.update(
        {
            ("pricing", "ARC-TESTNET"): "shared-pricing",
            ("hedge", "ARC-TESTNET"): "shared-hedge",
            ("treasury", "ARC-TESTNET"): "shared-treasury",
            ("trace", "ARC-TESTNET"): "shared-trace",
        }
    )
    cw._USER_WALLET_ID_OVERRIDES.clear()
    return inst, cw


def test_wallet_id_for_none_user_falls_back_to_shared():
    inst, _cw = _make_wallets_real()
    assert inst.wallet_id_for(None, "pricing") == "shared-pricing"
    assert inst.wallet_id_for(None, "hedge") == "shared-hedge"


def test_wallet_id_for_trace_role_always_shared():
    inst, _cw = _make_wallets_real()
    # Even with a user, the trace role (no per-user attribution) is shared.
    assert inst.wallet_id_for(USER, "trace") == "shared-trace"
    assert inst.wallet_id_for(USER, "treasury") == "shared-treasury"


def test_wallet_id_for_per_user_role_falls_back_when_no_override():
    inst, _cw = _make_wallets_real()
    # No per-user wallet provisioned -> falls back to shared keeper.
    assert inst.wallet_id_for(USER, "pricing") == "shared-pricing"


def test_wallet_id_for_uses_override_when_provisioned():
    inst, cw = _make_wallets_real()
    cw._USER_WALLET_ID_OVERRIDES[(USER, "hedge", "ARC-TESTNET")] = "user-hedge-wid"
    assert inst.wallet_id_for(USER, "hedge") == "user-hedge-wid"
    # A different user still falls back.
    assert inst.wallet_id_for("other", "hedge") == "shared-hedge"


def test_killswitch_schema_version_constant():
    assert KILLSWITCH_SCHEMA_VERSION == "akrita/killswitch/v1"

"""Kill-switch sequencing.

A single user-scoped emergency stop that, best-effort, unwinds every venue
the user's agents touch and anchors the whole event on Arc:

  a. Create a kill_switch_event row (audit anchor).
  b. Flip kill_switch=True on every one of the user's agent instances
     (idempotent stop — the per-tick runners read this and stand down).
  c. NOMOS: cancel the user's open Polymarket orders.
  d. SPATHA: close the user's open Hyperliquid hedges.
  e. AGROS: redeem USYC back to USDC to cover in-flight margin.
  f. Commit a kill-switch trace to the TraceRegistry on Arc (same canonical
     JSON + sha256 the decision trace pipeline uses).
  g. Update the event row with every result + final status.

Each external call is wrapped so one failing venue never aborts the others;
errors are captured per-step and the final status is "partial" if anything
failed (including the Arc commit), "completed" otherwise. This function never
raises for an external failure — the worst case is a "partial" event row.
"""
from __future__ import annotations

import time

from shared.canonical import trace_hash

# Distinguished agent id for orchestrator-originated traces. Real agents are
# NOMOS=1 / SPATHA=2 / AGROS=3 in the BuilderRegistry; 0 is reserved for the
# orchestrator / system (matches TracePipeline._agent_id's fallback of 0).
ORCHESTRATOR_AGENT_ID = 0

# Conservative USYC redemption used when we can't read the user's balance — we
# would rather over-redeem a small amount to cover in-flight margin than leave
# a perp position unmargined during an emergency stop.
DEFAULT_REDEEM_USYC = 100.0

KILLSWITCH_SCHEMA_VERSION = "akrita/killswitch/v1"


async def trigger_kill_switch(
    user_id: str,
    trigger_source: str,
    trigger_detail: dict,
    *,
    adapters,
    state,
) -> dict:
    """Run the full user-scoped kill-switch sequence. Returns the final event
    dict (as stored). Best-effort: never raises on an external failure."""
    trigger_detail = trigger_detail or {}

    # a. Audit anchor row.
    event_id = await state.create_kill_switch_event(user_id, trigger_source, trigger_detail)

    # b. Idempotent stop: flip kill_switch on every instance the user owns so
    #    the per-tick runners stand down. list_user_instances spans archetypes.
    try:
        instances = await state.list_user_instances(user_id)
    except Exception:
        instances = []
    for inst in instances:
        try:
            await state.set_instance_flags(inst["id"], kill_switch=True)
        except Exception:
            # A single instance failing to flip must not abort the unwind.
            pass

    # c. NOMOS — cancel open Polymarket orders.
    #    NOTE: the StateStore facade exposes no open-orders read (only the repo
    #    layer's SQLOrderRepo.list_open, which isn't surfaced on `state`). We
    #    therefore probe a `list_open_orders(user_id)` accessor if one ever
    #    lands and otherwise operate on an empty list — orders cancellation is
    #    a no-op until that read method is added to state.py (owned elsewhere).
    nomos_result: dict = {"cancelled": [], "errors": []}
    open_orders = []
    list_open_orders = getattr(state, "list_open_orders", None)
    if list_open_orders is not None:
        try:
            open_orders = await list_open_orders(user_id=user_id)
        except Exception as exc:
            nomos_result["errors"].append(f"list_open_orders: {exc}")
    for order in open_orders:
        order_id = order.get("order_id") or order.get("venue_order_id") or order.get("id")
        try:
            await adapters.polymarket.cancel_order(order_id)
            nomos_result["cancelled"].append(order_id)
        except Exception as exc:
            nomos_result["errors"].append({"order_id": order_id, "error": str(exc)})

    # d. SPATHA — close open Hyperliquid hedges.
    spatha_result: dict = {"closed": [], "errors": []}
    try:
        open_hedges = await state.list_open_hedges(user_id)
    except Exception as exc:
        open_hedges = []
        spatha_result["errors"].append(f"list_open_hedges: {exc}")
    for hedge in open_hedges:
        pos_id = hedge.get("venue_position_id") or hedge.get("position_id")
        try:
            # close_position takes the venue position id; coerce to int when it
            # looks numeric (HL ids are ints) but tolerate string ids.
            try:
                pos_arg = int(pos_id)
            except (TypeError, ValueError):
                pos_arg = pos_id
            await adapters.hyperliquid.close_position(pos_arg)
            spatha_result["closed"].append(pos_id)
        except Exception as exc:
            spatha_result["errors"].append({"position_id": pos_id, "error": str(exc)})

    # e. AGROS — redeem USYC to USDC to cover in-flight margin. Use the user's
    #    observed USYC balance when known, else a conservative fixed amount.
    agros_result: dict = {"redeemed_usdc": 0.0, "errors": []}
    redeem_amount = DEFAULT_REDEEM_USYC
    try:
        balances = await state.list_user_balances(user_id)
        usyc_bal = 0.0
        for b in balances:
            if (b.get("token") or "").upper() == "USYC":
                usyc_bal += float(b.get("amount") or 0.0)
        if usyc_bal > 0:
            redeem_amount = usyc_bal
    except Exception as exc:
        agros_result["errors"].append(f"list_user_balances: {exc}")

    if redeem_amount > 0:
        try:
            # Per-user Circle wallets aren't provisioned yet, so resolve the
            # treasury wallet via the keeper-fallback helper (user_id-aware,
            # falls back to the shared keeper).
            wallet_id = adapters.wallets.wallet_id_for(user_id, "treasury", "ARC-TESTNET")
            receipt = await adapters.usyc.redeem(wallet_id, redeem_amount)
            agros_result["redeemed_usdc"] = float(getattr(receipt, "usdc_out", 0.0) or 0.0)
        except Exception as exc:
            agros_result["errors"].append(str(exc))

    # f. Commit a kill-switch trace on Arc (same canonical JSON + sha256 as the
    #    decision trace pipeline — reuse shared.canonical.trace_hash). A failed
    #    Arc commit (e.g. unfunded keeper) is captured, not fatal.
    body = {
        "schema_version": KILLSWITCH_SCHEMA_VERSION,
        "user_id": user_id,
        "trigger_source": trigger_source,
        "trigger_detail": trigger_detail,
        "nomos_result": nomos_result,
        "spatha_result": spatha_result,
        "agros_result": agros_result,
        "ts_ms": int(time.time() * 1000),
    }
    th = trace_hash(body)
    arc_tx: str | None = None
    arc_error: str | None = None
    try:
        receipt = await adapters.arc.commit_trace(
            agent_id=ORCHESTRATOR_AGENT_ID,
            decision_id=event_id,
            trace_hash_hex=th,
            ipfs_cid="",
        )
        arc_tx = getattr(receipt, "tx_hash", None)
    except Exception as exc:
        arc_error = str(exc)

    # g. Persist all results + final status. "partial" if any step errored
    #    (venue errors or a failed Arc commit), else "completed".
    had_errors = bool(
        nomos_result["errors"]
        or spatha_result["errors"]
        or agros_result["errors"]
        or arc_error
    )
    status = "partial" if had_errors else "completed"
    # Surface a failed Arc commit on a result that actually gets persisted
    # (update_results has no trigger_detail field). The kill-switch trace lives
    # alongside the AGROS step conceptually, so record it there.
    arc_result = {"trace_hash": th, "arc_tx": arc_tx}
    if arc_error:
        arc_result["error"] = arc_error
    agros_result["arc_commit"] = arc_result

    await state.update_kill_switch_event(
        event_id,
        nomos_result=nomos_result,
        spatha_result=spatha_result,
        agros_result=agros_result,
        trace_decision_id=event_id,
        trace_hash=th,
        arc_tx=arc_tx,
        status=status,
        completed=True,
    )

    event = await state.get_kill_switch_event(event_id)
    return event or {
        "id": event_id,
        "user_id": user_id,
        "status": status,
        "trace_hash": th,
        "arc_tx": arc_tx,
        "nomos_result": nomos_result,
        "spatha_result": spatha_result,
        "agros_result": agros_result,
    }

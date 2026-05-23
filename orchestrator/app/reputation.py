"""ERC-8004 reputation aggregation.

AKRITA keeps a *signed* off-chain feedback ledger (`feedback_events`): every
maker fill, resolved Brier score, hedge PnL realisation, and yield accrual
records a `delta`. This module rolls that ledger up into a single uint64
ERC-8004 score in the BuilderRegistry's `[0, 10000]` range and prepares the
on-chain `updateReputation(agentId, score)` push.

On-chain push policy (deliberate):
  - `push_reputation(..., dry_run=True)` is the DEFAULT and only RETURNS the
    planned call. Nothing is broadcast.
  - A real push requires (a) a `reputationOracle` to be set on the
    BuilderRegistry (the contract constructor seeds it to the deployer; the
    AKRITA reputation pusher must be granted that role first) AND (b) an
    adapter that exposes an `update_reputation` capability. Until both exist,
    even `dry_run=False` falls back to held (no broadcast) with a clear note.

This keeps the module import-safe (no adapter / DB construction at import
time) and keeps the actual on-chain write behind a human.
"""
from __future__ import annotations

from typing import Any, Optional

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

# BuilderRegistry stores reputation as a uint64 clamped to [0, 10000] and seeds
# new agents at 5000 (the midpoint). We score relative to that baseline.
SCORE_MIN = 0
SCORE_MAX = 10_000
SCORE_BASELINE = 5_000

# event_type -> weight. Each weight is the score contribution per unit of the
# component's natural magnitude (see `score_from_components`). Volume is scored
# per-USDC at a small rate so a few hundred USDC of maker flow meaningfully
# moves the score without a single whale saturating it. Brier is a [0,1]
# accuracy-style signal scaled up. Hedge PnL / yield are USDC deltas.
WEIGHTS: dict[str, float] = {
    "maker_volume": 1.0,      # per attributed maker-volume "point" (see below)
    "brier_resolved": 800.0,  # per unit of (positive) resolved Brier credit
    "hedge_pnl": 5.0,         # per USDC of realised hedge PnL
    "yield_accrued": 8.0,     # per USDC of accrued treasury yield
}

# Maker volume is fed in as USDC; convert to "points" before weighting so the
# WEIGHTS table reads in consistent units. 50 USDC of maker volume == 1 point.
_VOLUME_USDC_PER_POINT = 50.0


def score_from_components(components: dict[str, float]) -> int:
    """Map a {component -> magnitude} dict to a uint64-safe ERC-8004 score.

    Monotonic and non-decreasing in every positive component (notably volume):
    more attributed maker volume can only raise the score. The result is the
    BuilderRegistry baseline (5000) plus the weighted sum, clamped to
    [0, 10000] so it is always a valid uint64 the contract will accept.
    """
    contribution = 0.0
    for name, weight in WEIGHTS.items():
        magnitude = float(components.get(name, 0.0) or 0.0)
        if name == "maker_volume":
            magnitude = magnitude / _VOLUME_USDC_PER_POINT
        contribution += weight * magnitude

    raw = SCORE_BASELINE + contribution
    score = int(round(raw))
    # Clamp to the contract-valid uint64 range.
    if score < SCORE_MIN:
        score = SCORE_MIN
    if score > SCORE_MAX:
        score = SCORE_MAX
    return score


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _components_from_feedback(by_type: dict[str, Any], attributed_volume_usdc: float) -> dict[str, float]:
    """Build the scoring components dict from a per-type feedback rollup.

    `by_type` is the {event_type: {total_delta, count}} shape produced by
    `state.feedback_by_user()`. Attributed maker volume is sourced from the
    fill ledger (`volume_by_user`) rather than feedback deltas so the volume
    component reflects real Polymarket flow even before maker_volume feedback
    rows are written.
    """
    def _delta(et: str) -> float:
        entry = by_type.get(et) or {}
        return float(entry.get("total_delta", 0.0) or 0.0)

    return {
        "maker_volume": float(attributed_volume_usdc or 0.0),
        "brier_resolved": _delta("brier_resolved"),
        "hedge_pnl": _delta("hedge_pnl"),
        "yield_accrued": _delta("yield_accrued"),
    }


async def compute_reputation_summary(user_id: str, *, state: Any = None) -> dict:
    """Aggregate a user's off-chain reputation ledger into a public summary.

    Returns the ERC-8004 id (the builder's on-chain agentId), the net signed
    delta, the per-type breakdown, attributed maker volume, the trace anchor
    count, and the scoring `components` (so the public /akritai page can show
    *why* a score is what it is).
    """
    if state is None:
        from orchestrator.app.state import state as _state
        state = _state

    fb_all = await state.feedback_by_user()
    fb = fb_all.get(user_id, {"total_delta": 0.0, "count": 0, "by_type": {}})
    by_type = fb.get("by_type", {})

    volume = (await state.volume_by_user()).get(user_id, {})
    attributed_volume_usdc = float(volume.get("volume", 0.0) or 0.0)

    trace_counts = await state.trace_count_by_user()
    trace_count = int(trace_counts.get(user_id, 0) or 0)

    profile = await state.get_builder_profile(user_id)
    erc8004_id = profile.get("onchain_agent_id") if profile else None

    components = _components_from_feedback(by_type, attributed_volume_usdc)
    score = score_from_components(components)

    return {
        "user_id": user_id,
        "erc8004_id": erc8004_id,
        "total_delta": float(fb.get("total_delta", 0.0) or 0.0),
        "by_type": by_type,
        "attributed_volume_usdc": attributed_volume_usdc,
        "trace_count": trace_count,
        "score": score,
        "components": components,
    }


# ---------------------------------------------------------------------------
# On-chain push (prepared / held)
# ---------------------------------------------------------------------------

def _planned_call(agent_id: Optional[int], score: int) -> dict:
    """The BuilderRegistry.updateReputation(agentId, score) call we *would*
    broadcast — surfaced verbatim so a human can review it before signing."""
    return {
        "contract": "BuilderRegistry",
        "method": "updateReputation",
        "args": {"agentId": agent_id, "newScore": score},
        "abi_signature": "updateReputation(uint256,uint64)",
    }


def _oracle_capability(adapters: Any):
    """Return the first adapter exposing an `update_reputation` capability, or
    None. The arc adapter currently has no such method (the BuilderRegistry
    reputation push is not yet wired), so this returns None until that lands —
    keeping the push held by construction."""
    for name in ("builder", "arc"):
        adapter = getattr(adapters, name, None)
        if adapter is not None and callable(getattr(adapter, "update_reputation", None)):
            return adapter
    return None


async def push_reputation(
    user_id: str,
    *,
    adapters: Any,
    state: Any,
    dry_run: bool = True,
) -> dict:
    """Aggregate a user's unpushed feedback, compute the score, and prepare the
    BuilderRegistry.updateReputation push.

    DEFAULT is `dry_run=True`: returns the planned call WITHOUT broadcasting
    and without marking feedback pushed. A real broadcast (dry_run=False) also
    requires a reputation-oracle-capable adapter; absent one, we still hold and
    return a clear note (the BuilderRegistry `reputationOracle` must be set to
    the AKRITA pusher and an `update_reputation` adapter capability added — both
    are follow-ups).
    """
    summary = await compute_reputation_summary(user_id, state=state)
    score = summary["score"]
    agent_id = summary["erc8004_id"]

    # The unpushed feedback ids this push would cover (so a later real push can
    # mark exactly these). list_feedback returns rows with id + onchain_tx.
    rows = await state.list_feedback(user_id, 1000)
    unpushed_ids = [int(r["id"]) for r in rows if not r.get("onchain_tx")]

    planned = _planned_call(agent_id, score)
    base = {
        "user_id": user_id,
        "erc8004_id": agent_id,
        "score": score,
        "components": summary["components"],
        "unpushed_feedback_ids": unpushed_ids,
        "planned_call": planned,
    }

    if agent_id is None:
        return {
            **base,
            "broadcast": False,
            "held": True,
            "note": "no on-chain agentId for this user — register the builder first",
        }

    if dry_run:
        return {
            **base,
            "broadcast": False,
            "held": True,
            "dry_run": True,
            "note": "dry-run (default): on-chain push held for a human; nothing broadcast",
        }

    oracle = _oracle_capability(adapters)
    if oracle is None:
        return {
            **base,
            "broadcast": False,
            "held": True,
            "dry_run": False,
            "note": (
                "no reputation-oracle capability configured — set BuilderRegistry."
                "reputationOracle to the AKRITA pusher and add an adapter "
                "update_reputation(agentId, score) method; push held"
            ),
        }

    receipt = await oracle.update_reputation(int(agent_id), int(score))
    tx_hash = getattr(receipt, "tx_hash", None) or (
        receipt.get("tx_hash") if isinstance(receipt, dict) else None
    )
    if unpushed_ids and tx_hash:
        await state.mark_feedback_pushed(unpushed_ids, tx_hash)

    return {
        **base,
        "broadcast": True,
        "held": False,
        "dry_run": False,
        "tx_hash": tx_hash,
        "note": "reputation pushed on-chain; covered feedback marked pushed",
    }

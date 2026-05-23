"""Per-instance keeper liveness (mounted at /api/health).

The app already exposes a flat /health; this router gives the richer
per-instance view the operator console needs. For every enabled agent
instance (across the nomos/spatha/agros archetypes) it derives last-activity
from `state.decision_stats_by_user()` — specifically the most recent decision
timestamp for that user under the instance's archetype role — and flags an
instance as *stale* if it hasn't produced a decision within a per-archetype
threshold.

Thresholds are a small multiple (3x) of each archetype's tick cadence, so a
single missed tick is tolerated but a stalled keeper is caught quickly:

  - nomos  (pricing,  ~60s tick)  -> 180_000 ms
  - spatha (hedge,    ~30s tick)  -> 90_000 ms
  - agros  (treasury, ~120s tick) -> 360_000 ms

Defensive throughout: empty stats, instances with no decisions yet, and
unknown archetypes all degrade gracefully (treated as stale / default
threshold) rather than raising.
"""
from __future__ import annotations

import time

from fastapi import APIRouter

from orchestrator.app.state import state

router = APIRouter()

# Per-archetype staleness thresholds in milliseconds (3x the tick cadence).
STALENESS_THRESHOLDS_MS: dict[str, int] = {
    "nomos": 60_000 * 3,    # 180s
    "spatha": 30_000 * 3,   # 90s
    "agros": 120_000 * 3,   # 360s
}

# Fallback for any archetype we don't have an explicit cadence for.
_DEFAULT_THRESHOLD_MS = 180_000


def _threshold_for(archetype: str) -> int:
    return STALENESS_THRESHOLDS_MS.get(archetype, _DEFAULT_THRESHOLD_MS)


async def _instance_health() -> dict:
    now_ms = int(time.time() * 1000)

    # Cross-user decision stats: {user_id: {decisions, last_ts_ms, by_role}}.
    try:
        stats = await state.decision_stats_by_user() or {}
    except Exception:
        stats = {}

    # All enabled instances across every archetype.
    try:
        instances = await state.list_enabled_instances() or []
    except Exception:
        instances = []

    rows: list[dict] = []
    for inst in instances:
        user_id = inst.get("user_id")
        archetype = inst.get("archetype") or ""

        user_stats = stats.get(user_id, {}) if isinstance(stats, dict) else {}
        by_role = user_stats.get("by_role", {}) if isinstance(user_stats, dict) else {}
        role_stats = by_role.get(archetype, {}) if isinstance(by_role, dict) else {}

        last_active_ms = int(role_stats.get("last_ts_ms", 0) or 0)
        threshold_ms = _threshold_for(archetype)

        if last_active_ms <= 0:
            # Never produced a decision under this role yet -> stale.
            age_ms = None
            stale = True
        else:
            age_ms = max(0, now_ms - last_active_ms)
            stale = age_ms > threshold_ms

        rows.append(
            {
                "instance_id": inst.get("id"),
                "user_id": user_id,
                "archetype": archetype,
                "name": inst.get("name"),
                "last_active_ms": last_active_ms,
                "age_ms": age_ms,
                "threshold_ms": threshold_ms,
                "stale": stale,
            }
        )

    stale_n = sum(1 for r in rows if r["stale"])
    total = len(rows)
    return {
        "ts_ms": now_ms,
        "instances": rows,
        "summary": {"total": total, "stale": stale_n, "live": total - stale_n},
    }


@router.get("/instances")
async def instances() -> dict:
    """Per-instance liveness with per-archetype staleness flags."""
    return await _instance_health()


@router.get("")
async def health() -> dict:
    """Overall keeper health: live vs stale instance counts."""
    data = await _instance_health()
    summary = data["summary"]
    return {
        "status": "ok",
        "instances_live": summary["live"],
        "instances_stale": summary["stale"],
    }

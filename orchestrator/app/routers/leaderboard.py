"""Public per-user leaderboard — the traction artifact.

One unauthenticated endpoint aggregating, per user: their on-chain builder
registration (verifiable via BuilderRegistry.getBuilderCode), Polymarket
fill volume + builder fees, the count of on-chain trace anchors + the latest
trace hash (clickable to Arcscan + IPFS), and agent activity (decision count
+ last-seen). USYC yield context (APY/NAV) is shown once, globally.

Responses are cached in-process for a few seconds so a polling dashboard
doesn't hammer the chain reads.
"""
from __future__ import annotations

import time

from fastapi import APIRouter

from adapters import get_adapters
from orchestrator.app.state import state
from shared.config import settings

router = APIRouter()

_CACHE_TTL_S = 8.0
_cache: dict = {"ts": 0.0, "data": None}


def _explorer_tx(tx: str | None) -> str | None:
    if not tx:
        return None
    return f"{settings.arc_explorer_url.rstrip('/')}/tx/{tx}"


def _ipfs_url(cid: str | None) -> str | None:
    if not cid:
        return None
    return f"https://ipfs.io/ipfs/{cid}"


async def _build() -> dict:
    users = await state.list_users(include_system=True)
    profiles = {p["user_id"]: p for p in await state.list_builder_profiles()}
    volume = await state.volume_by_user()
    trace_counts = await state.trace_count_by_user()
    latest_traces = await state.latest_trace_by_user()
    dstats = await state.decision_stats_by_user()

    # USYC yield context (global) — best-effort live read.
    usyc_apy = usyc_nav = None
    try:
        adapters = get_adapters()
        usyc_apy = await adapters.usyc.get_current_yield_apy()
        usyc_nav = await adapters.usyc.get_nav_per_share()
    except Exception:
        pass

    rows = []
    for u in users:
        uid = u["id"]
        prof = profiles.get(uid, {})
        vol = volume.get(uid, {})
        lt = latest_traces.get(uid)
        ds = dstats.get(uid, {})
        rows.append(
            {
                "user_id": uid,
                "handle": u["handle"],
                "display_name": u.get("display_name"),
                "is_system": bool(u.get("is_system")),
                "msca_address": u.get("msca_address"),
                "builder_code": prof.get("builder_code"),
                "onchain_agent_id": prof.get("onchain_agent_id"),
                "registration_status": prof.get("registration_status"),
                "registration_tx": prof.get("registration_tx"),
                "registration_tx_url": _explorer_tx(prof.get("registration_tx")),
                "attributed_volume_usdc": float(vol.get("volume", 0.0)),
                "builder_fees_usdc": float(vol.get("fees", 0.0)),
                "fills": int(vol.get("fills", 0)),
                "trace_count": int(trace_counts.get(uid, 0)),
                "decisions": int(ds.get("decisions", 0)),
                "last_active_ms": int(ds.get("last_ts_ms", 0)),
                "by_role": ds.get("by_role", {}),
                "latest_trace": (
                    {
                        "trace_hash": lt["trace_hash"],
                        "decision_id": lt["decision_id"],
                        "agent_role": lt["agent_role"],
                        "arc_tx": lt.get("arc_tx"),
                        "arc_tx_url": _explorer_tx(lt.get("arc_tx")),
                        "cid": lt.get("cid"),
                        "ipfs_url": _ipfs_url(lt.get("cid")),
                        "committed_at": lt.get("committed_at"),
                    }
                    if lt
                    else None
                ),
            }
        )

    # Rank: volume desc, then on-chain trace anchors desc, then decisions desc.
    rows.sort(
        key=lambda r: (r["attributed_volume_usdc"], r["trace_count"], r["decisions"]),
        reverse=True,
    )
    for i, r in enumerate(rows, start=1):
        r["rank"] = i

    summary = {
        "users": len([r for r in rows if not r["is_system"]]),
        "total_users": len(rows),
        "total_volume_usdc": round(sum(r["attributed_volume_usdc"] for r in rows), 6),
        "total_builder_fees_usdc": round(sum(r["builder_fees_usdc"] for r in rows), 6),
        "total_fills": sum(r["fills"] for r in rows),
        "total_traces": sum(r["trace_count"] for r in rows),
        "total_decisions": sum(r["decisions"] for r in rows),
        "registered_builders": len(
            [r for r in rows if r["registration_status"] == "registered"]
        ),
        "usyc_apy": usyc_apy,
        "usyc_nav": usyc_nav,
        "builder_registry": settings.builder_registry_addr,
        "trace_registry": settings.trace_registry_addr,
        "explorer": settings.arc_explorer_url,
    }
    return {"ts_ms": int(time.time() * 1000), "summary": summary, "leaderboard": rows}


@router.get("")
async def leaderboard(fresh: bool = False) -> dict:
    now = time.monotonic()
    if not fresh and _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL_S:
        return _cache["data"]
    data = await _build()
    _cache["data"] = data
    _cache["ts"] = now
    return data

"""
AGROS — Treasury Agent.

Greek: agros = the cultivated field, the daily source of the polis's
sustenance. AGROS's mandate is that no dollar sits idle. It sweeps
USDC ↔ USYC every sweep interval, optimizing against projected
next-60min outflow.

Math: keep enough USDC to cover predicted outflow × safety_buffer_fraction
(floored at redemption_buffer_usd); sweep the surplus into USYC; redeem only
when an imminent fill is predicted to drain operational USDC below the floor.
The pure decision logic lives in ``treasury.py``; this module is the
orchestration shell (fetch balances, loop over tenants, submit decisions).

Multi-tenant: each tick we enumerate enabled AGROS instances from the
orchestrator and process each independently under its own AgrosParams. If the
instance registry is unavailable (or empty) we fall back to a single system
instance with defaults — preserving pre-multitenant behavior.

This is the agent that delivers the project's thesis. Without it,
capital sits idle in USDC earning zero. With it, capital earns
USYC yield 95% of the time and converts to operating margin in
seconds when needed.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from shared.config import settings
from shared.canonical import trace_hash
from shared.models import SYSTEM_USER_ID, TreasuryAction, TreasuryDecision
from shared.params import AgrosParams, validate_params

from agents.agros import treasury

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [AGROS] %(message)s",
)
log = logging.getLogger("agros")

ORCHESTRATOR_URL = settings.orchestrator_url
SWEEP_INTERVAL = settings.treasury_sweep_interval
MIN_USDC_BUFFER = settings.min_usdc_buffer
USYC_MIN_SUBSCRIBE = settings.usyc_min_subscribe
PROJECTED_OUTFLOW = settings.treasury_projected_outflow_usdc

# Map TreasuryAction enum onto the lower-case action strings returned by the
# pure treasury module.
_ACTION_ENUM = {
    "usyc_subscribe": TreasuryAction.USYC_SUBSCRIBE,
    "usyc_redeem": TreasuryAction.USYC_REDEEM,
    "noop": TreasuryAction.NOOP,
}

_decision_counter = 0

# Last-known live USYC APY, refreshed each balances fetch and reused so the
# narrative always carries a sensible yield even if a single read returns 0.0.
_last_known_apy = 0.0


def _next_id() -> int:
    global _decision_counter
    _decision_counter += 1
    return _decision_counter


async def fetch_instances() -> list[dict]:
    """Enumerate enabled AGROS instances from the orchestrator registry.

    Shape: {"instances": [{"id", "user_id", "params", "kill_switch", "enabled"}]}.
    On any failure or empty result the caller falls back to a single system
    instance with defaults (see ``_system_fallback_instance``).
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(
            f"{ORCHESTRATOR_URL}/api/instances",
            params={"archetype": "agros", "enabled": "true"},
        )
        resp.raise_for_status()
        return resp.json().get("instances", []) or []


def _system_fallback_instance() -> dict:
    """The single pre-multitenant instance: system tenant, default params."""
    return {
        "id": None,
        "user_id": SYSTEM_USER_ID,
        "params": {},
        "kill_switch": False,
        "enabled": True,
    }


async def fetch_balances() -> dict:
    """Fetch all balances and refresh the last-known USYC APY."""
    global _last_known_apy
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{ORCHESTRATOR_URL}/state/balances")
        resp.raise_for_status()
        balances = resp.json()
    apy = balances.get("usyc_apy")
    if isinstance(apy, (int, float)) and apy > 0:
        _last_known_apy = float(apy)
    return balances


async def forecast_outflow_60min() -> float:
    """Projected next-60min USDC outflow.

    Configurable flat estimate (treasury_projected_outflow_usdc) until the
    live projection (open orders + expected fills + pending hedge margin +
    reserve policy) is wired per docs/LIVE_IMPLEMENTATION_PLAN.md Phase 6.
    """
    return PROJECTED_OUTFLOW


def build_decision(
    instance: dict,
    params: AgrosParams,
    balances: dict,
    projected_outflow: float,
    apy: float,
) -> TreasuryDecision:
    """Build the per-tenant TreasuryDecision (always returns one, possibly NOOP).

    Tier handling (kept deliberately minimal and honest):
      * Tier A — USYC only. The baseline sweep behavior.
      * Tier B — USYC + an Aave supply path above an auto rate-floor. No Aave
        adapter exists in this codebase, so Tier B currently behaves IDENTICALLY
        to Tier A (USYC only). TODO: when an Aave adapter lands, route the
        surplus to whichever of USYC / Aave clears the auto rate-floor. We do NOT
        invent an adapter here.
      * Tier C — may additionally target pendle_pt_fraction / susde_fraction, but
        ONLY when ``treasury.tier_allows_susde`` is satisfied (Tier C AND explicit
        sUSDe cooldown acceptance). Otherwise it degrades to USYC-only like A/B.
        The sUSDe/Pendle execution adapters are likewise not present, so for now
        the USYC sweep still carries the position; the gate exists so the agent
        never *allocates* to sUSDe without acceptance.
    """
    agros = balances.get("agros-keeper", {})
    arc_balance = agros.get("arc", {})
    current_usdc = arc_balance.get("USDC", 0.0)
    current_usyc = arc_balance.get("USYC", 0.0)

    buffer = treasury.target_buffer(projected_outflow, params)
    action_str, amount = treasury.decide_action(
        current_usdc=current_usdc,
        projected_outflow=projected_outflow,
        params=params,
        min_subscribe=USYC_MIN_SUBSCRIBE,
    )

    # Tier C with accepted cooldown may allocate part of the sweep to sUSDe /
    # Pendle PT. No execution adapter exists yet, so we record intent in the
    # rationale rather than emitting a separate decision; USYC remains the
    # carrier. Without acceptance (or below Tier C) this is a no-op and the
    # instance behaves exactly like Tier A/B.
    susde_allowed = treasury.tier_allows_susde(params)

    # A redeem is bounded by what we actually hold in USYC (less a hair for NAV
    # drift), in addition to the per-action cap already applied upstream.
    if action_str == "usyc_redeem":
        amount = min(amount, current_usyc * 0.99)
        if amount < USYC_MIN_SUBSCRIBE:
            action_str, amount = "noop", 0.0

    rationale = {
        "tier": params.tier,
        "user_id": instance["user_id"],
        "current_usdc": current_usdc,
        "current_usyc": current_usyc,
        "projected_outflow": projected_outflow,
        "target_buffer": buffer,
        "surplus": current_usdc - buffer,
        "safety_buffer_fraction": params.safety_buffer_fraction,
        "redemption_buffer_usd": params.redemption_buffer_usd,
        "susde_allowed": susde_allowed,
        "pendle_pt_fraction": params.pendle_pt_fraction,
        "susde_fraction": params.susde_fraction,
        "action": action_str,
        "amount": round(amount, 2),
    }

    narrative = treasury.humanize(
        action=action_str,
        amount=amount,
        projected_outflow=projected_outflow,
        buffer=buffer,
        apy=apy,
        tier=params.tier,
    )

    return TreasuryDecision(
        decision_id=_next_id(),
        nonce=int(time.time() * 1_000_000) % 2**31,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash(rationale),
        user_id=instance["user_id"],
        agent_instance_id=instance.get("id"),
        action=_ACTION_ENUM[action_str],
        amount=round(amount, 2),
        projected_outflow_60min=projected_outflow,
        safety_multiplier=params.safety_buffer_fraction,
        narrative=narrative,
    )


async def submit(decision: TreasuryDecision) -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                f"{ORCHESTRATOR_URL}/decisions/treasury",
                json=decision.model_dump(mode="json"),
            )
            if resp.status_code >= 400:
                log.warning("Treasury submit failed: %d %s",
                            resp.status_code, resp.text[:200])
            else:
                log.info("Treasury %d %s amount=%.2f → %s",
                         decision.decision_id, decision.action,
                         decision.amount,
                         resp.json().get("status"))
        except httpx.RequestError as e:
            log.error("Orchestrator unreachable: %s", e)


async def tick() -> None:
    """One sweep cycle: enumerate instances, decide, submit per tenant."""
    try:
        instances = await fetch_instances()
    except (httpx.HTTPError, ValueError) as e:
        log.debug("instance registry unavailable (%s); using system fallback", e)
        instances = []
    if not instances:
        instances = [_system_fallback_instance()]

    balances = await fetch_balances()
    projected_outflow = await forecast_outflow_60min()
    apy = _last_known_apy

    for inst in instances:
        try:
            if inst.get("kill_switch"):
                log.info("instance %s kill_switch engaged — skipping",
                         inst.get("id"))
                continue
            params = validate_params("agros", inst.get("params") or {})
            decision = build_decision(
                instance=inst,
                params=params,
                balances=balances,
                projected_outflow=projected_outflow,
                apy=apy,
            )
            await submit(decision)
        except Exception as e:  # one tenant must not break the others
            log.exception("instance %s failed: %s", inst.get("id"), e)


async def main() -> None:
    log.info("AGROS starting — sweep_interval=%ds, min_buffer=$%.0f",
             SWEEP_INTERVAL, MIN_USDC_BUFFER)
    while True:
        try:
            await tick()
        except Exception as e:
            log.exception("loop iteration failed: %s", e)
        await asyncio.sleep(SWEEP_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())

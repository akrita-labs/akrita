"""
AGROS — Treasury Agent.

Greek: agros = the cultivated field, the daily source of the polis's
sustenance. AGROS's mandate is that no dollar sits idle. It sweeps
USDC ↔ USYC every TREASURY_SWEEP_INTERVAL_SEC, optimizing against
projected next-60min outflow.

Math: keep enough USDC to cover predicted outflow × safety_multiplier;
sweep the surplus into USYC; redeem only when an imminent fill is
predicted to drain operational USDC below the floor.

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
from shared.models import TreasuryAction, TreasuryDecision

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [AGROS] %(message)s",
)
log = logging.getLogger("agros")

ORCHESTRATOR_URL = settings.orchestrator_url
SWEEP_INTERVAL = settings.treasury_sweep_interval
SAFETY_MULTIPLIER = settings.safety_multiplier
MIN_USDC_BUFFER = settings.min_usdc_buffer
USYC_MIN_SUBSCRIBE = settings.usyc_min_subscribe


_decision_counter = 0


def _next_id() -> int:
    global _decision_counter
    _decision_counter += 1
    return _decision_counter


async def fetch_balances() -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{ORCHESTRATOR_URL}/state/balances")
        resp.raise_for_status()
        return resp.json()


async def forecast_outflow_60min() -> float:
    """Projected next-60min USDC outflow.

    Conservative flat estimate until the live projection (open orders +
    expected fills + pending hedge margin + reserve policy) is wired per
    docs/LIVE_IMPLEMENTATION_PLAN.md Phase 6.
    """
    return 200.0


async def build_decision() -> TreasuryDecision | None:
    """Decide whether to subscribe, redeem, transfer, or do nothing."""
    balances = await fetch_balances()

    agros = balances.get("agros-keeper", {})
    arc_balance = agros.get("arc", {})
    current_usdc = arc_balance.get("USDC", 0.0)
    current_usyc = arc_balance.get("USYC", 0.0)

    projected_outflow = await forecast_outflow_60min()
    target_usdc = max(MIN_USDC_BUFFER, projected_outflow * SAFETY_MULTIPLIER)
    surplus = current_usdc - target_usdc

    rationale = {
        "current_usdc": current_usdc,
        "current_usyc": current_usyc,
        "projected_outflow": projected_outflow,
        "target_usdc": target_usdc,
        "surplus": surplus,
        "safety_multiplier": SAFETY_MULTIPLIER,
    }

    decision_base = dict(
        decision_id=_next_id(),
        nonce=int(time.time() * 1_000_000) % 2**31,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash(rationale),
        projected_outflow_60min=projected_outflow,
        safety_multiplier=SAFETY_MULTIPLIER,
    )

    if surplus >= USYC_MIN_SUBSCRIBE:
        # Sweep surplus into USYC
        return TreasuryDecision(
            **decision_base,
            action=TreasuryAction.USYC_SUBSCRIBE,
            amount=round(surplus, 2),
        )

    if surplus < -USYC_MIN_SUBSCRIBE:
        # Need to redeem USYC to bring USDC back above floor
        deficit = -surplus
        # Only redeem what we have
        redeem_amount = min(deficit, current_usyc * 0.99)
        if redeem_amount < USYC_MIN_SUBSCRIBE:
            return None  # below threshold, do nothing
        return TreasuryDecision(
            **decision_base,
            action=TreasuryAction.USYC_REDEEM,
            amount=round(redeem_amount, 2),
        )

    return None  # no action this tick


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


async def main() -> None:
    log.info("AGROS starting — sweep_interval=%ds, safety=%.2fx",
             SWEEP_INTERVAL, SAFETY_MULTIPLIER)
    while True:
        try:
            decision = await build_decision()
            if decision:
                await submit(decision)
            else:
                log.debug("no action this tick")
        except Exception as e:
            log.exception("loop iteration failed: %s", e)
        await asyncio.sleep(SWEEP_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())

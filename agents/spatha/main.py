"""
SPATHA — Hedge Agent.

Greek: spatha = the heavy double-edged cavalry sword. SPATHA is the
tactical risk-containment force. It watches the global directional
exposure produced by NOMOS quoting; when the inventory delta breaches
the no-transaction band, it opens a delta-neutralizing perp position.

Loop: every HEDGE_CHECK_INTERVAL_SEC:
  1. List enabled spatha instances (multi-tenant); fall back to one system
     instance with default params when the registry is unavailable.
  2. Read the inventory snapshot from the orchestrator.
  3. Per instance, per market:
     a. Compute the Whalley-Wilmott no-transaction band from the instance's
        risk-aversion. Skip unless |exposure| breaches the band.
     b. Select a hedge instrument (direct perp, else correlated proxy) honoring
        the instance's underlying whitelist. Skip if nothing qualifies.
     c. Gate OPENs on the internal funding ceiling (CLOSEs always allowed).
     d. Clamp leverage to the instance cap and POST /decisions/hedge.

IMPORTANT: A hedge is a REAL price-bearing position on a correlated
instrument. Not a stable-to-stable swap. See proxy.select_hedge_instrument
for the mapping. The funding ceiling and the 1bp builder fee are INTERNAL
guardrails — they are never user-facing parameters.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from shared.config import settings
from shared.canonical import trace_hash
from shared.models import (
    SYSTEM_USER_ID,
    HedgeDecision,
    HedgeSide,
    HedgeVenue,
    MarginAsset,
)
from shared.params import (
    BUILDER_FEE_BPS,
    GAMMA,
    SLIPPAGE_BPS,
    SpathaParams,
    max_funding_bps_hr,
    validate_params,
)

from agents.spatha.hedge import (
    clamp_leverage,
    funding_ceiling_ok,
    hedge_side_for,
    no_transaction_band,
    should_hedge,
)
from agents.spatha.proxy import select_hedge_instrument

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [SPATHA] %(message)s",
)
log = logging.getLogger("spatha")

ORCHESTRATOR_URL = settings.orchestrator_url
HEDGE_INTERVAL = settings.hedge_check_interval

# Nominal taker fee on the hedge venue, bps. Combined with SLIPPAGE_BPS and the
# AKRITA builder fee this forms the round-trip proportional cost_rate that sets
# the no-transaction band width. INTERNAL — not a user field.
TAKER_FEE_BPS = 4

# Round-trip proportional trading cost as a fraction (slippage + taker + 1bp
# builder fee, both legs). Drives the no-transaction band.
COST_RATE = 2.0 * (SLIPPAGE_BPS + TAKER_FEE_BPS + BUILDER_FEE_BPS) / 10_000.0

# Reference notional used to scale the band when a row carries no exposure to
# proxy off (e.g. a flat market). PM shares settle in [0,1]; a hedge contract
# proxies a larger notional, so we floor the price proxy at this reference.
REFERENCE_PRICE_USD = 1_000.0

# PM shares per proxy contract (tiny: 1000 PM shares ~ 1 BTC contract proxy).
SHARES_PER_CONTRACT = 1_000.0

# Static market -> direct perp mapping. Real impl: a Postgres table or config.
# Markets absent here fall back to proxy selection via the correlation table.
MARKET_TO_INSTRUMENT = {
    "0xbbbb": "BTC-PERP",   # BTC price market — direct hedge
    "0xeeee": "ETH-PERP",   # ETH/BTC ratio — direct
    "BTC": "BTC-PERP",
    "ETH": "ETH-PERP",
    "SOL": "SOL-PERP",
}


_decision_counter = 0


def _next_id() -> int:
    global _decision_counter
    _decision_counter += 1
    return _decision_counter


async def fetch_inventory() -> list[dict]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{ORCHESTRATOR_URL}/state/inventory")
        resp.raise_for_status()
        return resp.json().get("inventory", [])


async def fetch_instances() -> list[dict]:
    """List enabled spatha instances from the orchestrator registry.

    Returns the raw instance dicts ({"id","user_id","params","kill_switch",
    "enabled"}). On any failure or an empty registry the caller falls back to a
    single system instance, so SPATHA never regresses to "does nothing".
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(
            f"{ORCHESTRATOR_URL}/api/instances",
            params={"archetype": "spatha", "enabled": "true"},
        )
        resp.raise_for_status()
        return resp.json().get("instances", [])


def _system_instance() -> dict:
    """The default single-tenant instance used when the registry is empty.

    Preserves pre-multitenant behavior: default SpathaParams, system user, no
    explicit agent_instance_id, never kill-switched.
    """
    return {
        "id": None,
        "user_id": SYSTEM_USER_ID,
        "params": {},
        "kill_switch": False,
        "enabled": True,
    }


async def get_active_instances() -> list[dict]:
    try:
        instances = await fetch_instances()
    except (httpx.HTTPError, ValueError) as e:
        log.debug("instance registry unavailable (%s); using system instance", e)
        instances = []
    if not instances:
        return [_system_instance()]
    return instances


async def build_hedges_for_instance(inst: dict, inventory: list[dict]) -> list[HedgeDecision]:
    """Construct hedge decisions for one instance across all inventory rows."""
    if inst.get("kill_switch"):
        return []

    params: SpathaParams = validate_params("spatha", inst.get("params") or {})
    a = params.hedge_band_risk_aversion
    ceiling = max_funding_bps_hr(a)

    user_id = inst.get("user_id") or SYSTEM_USER_ID
    instance_id = inst.get("id")

    decisions: list[HedgeDecision] = []
    for inv in inventory:
        decision = build_hedge(inv, params, a, ceiling, user_id, instance_id)
        if decision is not None:
            decisions.append(decision)
    return decisions


def build_hedge(
    inv: dict,
    params: SpathaParams,
    a: float,
    ceiling: float,
    user_id: str,
    instance_id: str | None,
) -> HedgeDecision | None:
    """If exposure breaches the band, construct a band-/whitelist-/funding-gated hedge."""
    exposure = inv["net_exposure"]
    market_id = inv["market_id"]

    # 1. No-transaction band: leave small drift un-hedged. The price proxy is
    #    the row's gross exposure (floored at REFERENCE_PRICE_USD), so the band
    #    scales with position notional — a large book tolerates more drift than
    #    a small one — while still shrinking with risk-aversion.
    price_proxy = max(abs(exposure), REFERENCE_PRICE_USD)
    band = no_transaction_band(a, COST_RATE, GAMMA, price_proxy)
    if not should_hedge(exposure, band):
        return None

    # 2. Instrument selection honoring the user's underlying whitelist.
    instrument, mode = select_hedge_instrument(
        market_id, params.hedge_underlying_whitelist, MARKET_TO_INSTRUMENT
    )
    if mode == "none" or instrument is None:
        log.info(
            "skip %s: no whitelisted hedge instrument (whitelist=%s)",
            market_id, params.hedge_underlying_whitelist,
        )
        return None

    # 3. Funding ceiling gates OPENs only; a CLOSE is always permitted.
    #    Live funding read is wired in the runtime; default 0 keeps the gate
    #    open until the adapter feeds a real rate.
    current_funding = float(inv.get("funding_bps_per_hr", 0.0))
    if not funding_ceiling_ok(current_funding, a):
        log.info(
            "skip OPEN %s: funding %.1fbps/hr > ceiling %.0fbps/hr (a=%.2f)",
            market_id, current_funding, ceiling, a,
        )
        return None

    side = HedgeSide.SHORT if hedge_side_for(exposure) == "short" else HedgeSide.LONG
    size = abs(exposure) / SHARES_PER_CONTRACT
    leverage = clamp_leverage(2.0, params.leverage_cap)
    margin = abs(exposure) * 0.5 / leverage  # notional / leverage

    narrative = (
        f"{side.value} {instrument} ({mode}) size {size:.4f}; "
        f"band ${band:.0f} @ a={a}; "
        f"funding {current_funding:.1f}bps/hr <= ceil {ceiling:.0f}"
    )

    rationale = {
        "trigger": "no_transaction_band_breach",
        "exposure": exposure,
        "instrument": instrument,
        "mode": mode,
        "hedge_side": side.value,
        "band_usd": band,
        "risk_aversion": a,
        "funding_bps_per_hr": current_funding,
        "funding_ceiling_bps_per_hr": ceiling,
        "leverage": leverage,
    }

    return HedgeDecision(
        decision_id=_next_id(),
        nonce=int(time.time() * 1_000_000) % 2**31,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash(rationale),
        user_id=user_id,
        agent_instance_id=instance_id,
        market_id=market_id,
        action="open",
        venue=HedgeVenue.HYPERLIQUID,
        instrument=instrument,
        side=side,
        size=size,
        leverage=leverage,
        margin_asset=MarginAsset.USDC,
        margin_amount=margin,
        stop_loss=None,
        narrative=narrative,
    )


async def submit(decision: HedgeDecision) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                f"{ORCHESTRATOR_URL}/decisions/hedge",
                json=decision.model_dump(mode="json"),
            )
            if resp.status_code >= 400:
                log.warning("Hedge submit failed: %d %s",
                            resp.status_code, resp.text[:200])
            else:
                log.info("Hedge %d open %s %s size=%.4f → %s",
                         decision.decision_id, decision.side,
                         decision.instrument, decision.size,
                         resp.json().get("status"))
        except httpx.RequestError as e:
            log.error("Orchestrator unreachable: %s", e)


async def main() -> None:
    log.info("SPATHA starting — interval=%ds, cost_rate=%.4f, gamma=%.2f",
             HEDGE_INTERVAL, COST_RATE, GAMMA)
    while True:
        try:
            instances = await get_active_instances()
            inventory = await fetch_inventory()
            for inst in instances:
                hedges = await build_hedges_for_instance(inst, inventory)
                for hedge in hedges:
                    await submit(hedge)
        except Exception as e:
            log.exception("loop iteration failed: %s", e)
        await asyncio.sleep(HEDGE_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())

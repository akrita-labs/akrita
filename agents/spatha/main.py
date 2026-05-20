"""
SPATHA — Hedge Agent.

Greek: spatha = the heavy double-edged cavalry sword. SPATHA is the
tactical risk-containment force. It watches the global directional
exposure produced by NOMOS quoting; when the inventory delta breaches
threshold, it opens a delta-neutralizing perp position.

Loop: every HEDGE_CHECK_INTERVAL_SEC:
  1. Read inventory snapshot from orchestrator
  2. For each market with |exposure| > threshold:
     a. Pick venue (HL primary, dYdX/GMX fallback)
     b. Compute hedge size + margin
     c. POST /decisions/hedge

IMPORTANT: A hedge is a REAL price-bearing position on a correlated
instrument. Not a stable-to-stable swap. See market_to_instrument()
for the mapping.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from shared.config import settings
from shared.canonical import trace_hash
from shared.models import (
    HedgeDecision,
    HedgeSide,
    HedgeVenue,
    MarginAsset,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [SPATHA] %(message)s",
)
log = logging.getLogger("spatha")

ORCHESTRATOR_URL = settings.orchestrator_url
HEDGE_INTERVAL = settings.hedge_check_interval
HEDGE_THRESHOLD = settings.hedge_inventory_threshold


# Mapping from market_id prefix -> reference perp instrument.
# Real impl: this lives in a Postgres table or config file.
MARKET_TO_INSTRUMENT = {
    "0xaaaa": "BTC-PERP",   # Fed rate cut market — correlated with rates -> BTC proxy
    "0xbbbb": "BTC-PERP",   # BTC price market — direct hedge
    "0xcccc": "ETH-PERP",   # ECB market — proxy via crypto volatility
    "0xdddd": "BTC-PERP",   # CPI market — BTC reacts to CPI
    "0xeeee": "ETH-PERP",   # ETH/BTC ratio — direct
}


_decision_counter = 0


def _next_id() -> int:
    global _decision_counter
    _decision_counter += 1
    return _decision_counter


def market_to_instrument(market_id: str) -> str:
    """Map a PM market to the perp instrument to hedge against."""
    prefix = market_id[:6]
    return MARKET_TO_INSTRUMENT.get(prefix, "BTC-PERP")


async def fetch_inventory() -> list[dict]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{ORCHESTRATOR_URL}/state/inventory")
        resp.raise_for_status()
        return resp.json().get("inventory", [])


async def build_hedge(inv: dict) -> HedgeDecision | None:
    """If exposure breaches threshold, construct a hedge decision."""
    exposure = inv["net_exposure"]
    if abs(exposure) < HEDGE_THRESHOLD:
        return None

    market_id = inv["market_id"]
    instrument = market_to_instrument(market_id)
    # Long YES on PM -> short the proxy; short YES on PM -> long the proxy
    side = HedgeSide.SHORT if exposure > 0 else HedgeSide.LONG
    size = abs(exposure) / 1000  # tiny: 1000 PM shares ~ 1 BTC contract proxy
    margin = abs(exposure) * 0.5  # 50% of exposure as margin; venue spec lookup wired in Phase 5

    rationale = {
        "trigger": "inventory_threshold_breach",
        "exposure": exposure,
        "instrument": instrument,
        "hedge_side": side.value,
    }

    return HedgeDecision(
        decision_id=_next_id(),
        nonce=int(time.time() * 1_000_000) % 2**31,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash(rationale),
        market_id=market_id,
        action="open",
        venue=HedgeVenue.HYPERLIQUID,
        instrument=instrument,
        side=side,
        size=size,
        leverage=2.0,
        margin_asset=MarginAsset.USDC,
        margin_amount=margin,
        stop_loss=None,
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
    log.info("SPATHA starting — threshold=%.1f, interval=%ds",
             HEDGE_THRESHOLD, HEDGE_INTERVAL)
    while True:
        try:
            inventory = await fetch_inventory()
            for inv in inventory:
                hedge = await build_hedge(inv)
                if hedge:
                    await submit(hedge)
        except Exception as e:
            log.exception("loop iteration failed: %s", e)
        await asyncio.sleep(HEDGE_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())

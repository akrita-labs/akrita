"""
NOMOS — Pricing Agent.

Greek: nomos = the norm, the decree, the geometric demarcation of
territory. NOMOS sits on the protocol frontier, quoting both sides
of subscribed Polymarket V2 markets to capture builder-code
attribution fees. It governs the bounds of the inventory.

Loop: every PRICING_QUOTE_INTERVAL_SEC, for each subscribed market:
  1. Fetch orderbook + recent fills
  2. Compute deterministic microprice + inventory-adjusted target
  3. Clamp to tradeable bounds
  4. POST /decisions/pricing to the orchestrator
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from adapters import get_adapters
from shared.canonical import trace_hash
from shared.models import AppetiteProfile, PricingDecision

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [NOMOS] %(message)s",
)
log = logging.getLogger("nomos")

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000")
QUOTE_INTERVAL = int(os.environ.get("PRICING_QUOTE_INTERVAL", "10"))
SUBSCRIBED_MARKETS = os.environ.get("SUBSCRIBED_MARKETS", "").split(",") or []
APPETITE = AppetiteProfile(os.environ.get("APPETITE_PROFILE", "balanced"))


# Local monotonic decision counter (orchestrator dedups by nonce)
_decision_counter = 0


def _next_id() -> int:
    global _decision_counter
    _decision_counter += 1
    return _decision_counter


async def compute_quote(market_id: str) -> PricingDecision | None:
    """Five-step pricing pipeline.

    1. Pull orderbook + recent fills
    2. Deterministic microprice
    3. Inventory skew
    4. Bounds clamp, then construct decision
    """
    adapters = get_adapters()

    book = await adapters.polymarket.get_orderbook(market_id, depth=10)
    if not book.bids or not book.asks:
        return None

    # 2. Deterministic microprice
    mid = book.microprice
    fair_spread = max(book.spread_bps / 10000, 0.005)

    # 3. Inventory skew — neutral until the live inventory read is wired
    #    (see docs/LIVE_IMPLEMENTATION_PLAN.md Phase 4).
    inv = 0.0
    skew = inv * 0.0001

    target_bid = mid - fair_spread / 2 - skew
    target_ask = mid + fair_spread / 2 - skew

    # 4. Clamp to tradeable bounds
    final_bid = max(0.02, min(0.98, target_bid))
    final_ask = max(0.02, min(0.98, target_ask))

    # Enforce bid < ask with minimum spread
    if final_ask - final_bid < 0.005:
        final_bid = max(0.02, mid - 0.0025)
        final_ask = min(0.98, mid + 0.0025)

    appetite_size = {
        AppetiteProfile.CONSERVATIVE: 50,
        AppetiteProfile.BALANCED: 100,
        AppetiteProfile.AGGRESSIVE: 200,
    }
    size = float(appetite_size[APPETITE])

    rationale = {
        "midpoint": mid,
        "spread_bps": book.spread_bps,
        "inventory_skew": inv,
        "appetite": APPETITE.value,
    }

    return PricingDecision(
        decision_id=_next_id(),
        nonce=int(time.time() * 1_000_000) % 2**31,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash(rationale),
        market_id=market_id,
        market_question=await adapters.polymarket.get_market_question(market_id),
        bid=round(final_bid, 4),
        ask=round(final_ask, 4),
        size=size,
        confidence=0.7,
        appetite_profile=APPETITE,
    )


async def submit(decision: PricingDecision) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                f"{ORCHESTRATOR_URL}/decisions/pricing",
                json=decision.model_dump(mode="json"),
            )
            if resp.status_code >= 400:
                log.warning("POST /decisions/pricing failed: %d %s",
                            resp.status_code, resp.text[:200])
            else:
                data = resp.json()
                log.info("Quote %d %s bid=%.4f ask=%.4f → %s",
                         decision.decision_id,
                         decision.market_id[:10] + "...",
                         decision.bid, decision.ask,
                         data.get("status"))
        except httpx.RequestError as e:
            log.error("Orchestrator unreachable: %s", e)


async def main() -> None:
    markets = [m for m in SUBSCRIBED_MARKETS if m]
    if not markets:
        log.warning(
            "NOMOS idle — no SUBSCRIBED_MARKETS configured. Set the env var "
            "to a comma-separated list of bytes32 market IDs to start quoting."
        )
        while True:
            await asyncio.sleep(QUOTE_INTERVAL)

    log.info("NOMOS starting — subscribed to %d markets, appetite=%s",
             len(markets), APPETITE.value)

    while True:
        for market_id in markets:
            try:
                decision = await compute_quote(market_id)
                if decision is not None:
                    await submit(decision)
            except Exception as e:
                log.exception("compute_quote/submit failed for %s: %s",
                              market_id[:10], e)
            await asyncio.sleep(QUOTE_INTERVAL / max(len(markets), 1))


if __name__ == "__main__":
    asyncio.run(main())

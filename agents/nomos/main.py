"""
NOMOS — Pricing Agent.

Greek: nomos = the norm, the decree, the geometric demarcation of
territory. NOMOS sits on the protocol frontier, quoting both sides
of subscribed Polymarket V2 markets to capture builder-code
attribution fees. It governs the bounds of the inventory.

Multi-tenant loop: every PRICING_QUOTE_INTERVAL_SEC,
  1. Fetch the set of enabled nomos instances from the orchestrator.
     (Falls back to a single synthetic "system" instance using NomosParams()
     defaults + env-configured markets so single-tenant behavior never
     regresses if the endpoint is unavailable.)
  2. For each instance (skipping any with kill_switch on):
       - validate its params, then for each subscribed market that passes the
         whitelist and is not breaker-tripped:
           a. Fetch orderbook + recent fills
           b. Compute a deterministic inventory-tilted quote (pricing.compute_quote)
           c. Tag the decision with user_id + agent_instance_id, author a one-line
              narrative, and POST /decisions/pricing to the orchestrator.

The quote math lives in the pure, import-safe `pricing` module; this file is the
network/IO shell around it.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from adapters import get_adapters
from agents.nomos import pricing
from shared.config import settings
from shared.canonical import trace_hash
from shared.models import SYSTEM_USER_ID, AppetiteProfile, PricingDecision
from shared.params import NomosParams, validate_params

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [NOMOS] %(message)s",
)
log = logging.getLogger("nomos")

ORCHESTRATOR_URL = settings.orchestrator_url
QUOTE_INTERVAL = settings.pricing_quote_interval
SUBSCRIBED_MARKETS = settings.subscribed_market_ids
APPETITE = AppetiteProfile(settings.appetite_profile)


# Local monotonic decision counter (orchestrator dedups by nonce)
_decision_counter = 0


def _next_id() -> int:
    global _decision_counter
    _decision_counter += 1
    return _decision_counter


async def fetch_instances() -> list[dict]:
    """Fetch enabled nomos instances from the orchestrator.

    Response shape: {"instances": [{"id","user_id","archetype","params",
    "kill_switch","enabled"}]}. On any failure (network, non-200, empty list)
    falls back to a single synthetic "system" instance carrying NomosParams()
    defaults and the env-configured markets, so single-tenant behavior never
    regresses.
    """
    fallback = [
        {
            "id": None,
            "user_id": SYSTEM_USER_ID,
            "archetype": "nomos",
            "params": {},  # validate_params -> NomosParams() defaults
            "kill_switch": False,
            "enabled": True,
            "markets": [m for m in SUBSCRIBED_MARKETS if m],
        }
    ]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{ORCHESTRATOR_URL}/api/instances",
                params={"archetype": "nomos", "enabled": "true"},
            )
            if resp.status_code >= 400:
                log.warning("GET /api/instances failed: %d — falling back to system instance",
                            resp.status_code)
                return fallback
            instances = resp.json().get("instances") or []
    except httpx.RequestError as e:
        log.warning("GET /api/instances unreachable (%s) — falling back to system instance", e)
        return fallback

    if not instances:
        return fallback
    return instances


def _instance_markets(inst: dict) -> list[str]:
    """Markets an instance quotes. The instances API does not (yet) carry a
    per-instance subscription list, so user instances quote the same
    env-configured markets the operator subscribes; the synthetic fallback
    instance carries them explicitly."""
    markets = inst.get("markets")
    if markets:
        return [m for m in markets if m]
    return [m for m in SUBSCRIBED_MARKETS if m]


async def compute_quote(
    market_id: str,
    params: NomosParams,
    inst: dict,
) -> PricingDecision | None:
    """Build a tenant-tagged PricingDecision for one market.

    1. Pull orderbook (skip if one-sided / empty).
    2. Derive mid + max_spread from the live book.
    3. Inventory ratio — neutral (0.5) until the live inventory read is wired
       (see docs/LIVE_IMPLEMENTATION_PLAN.md Phase 4).
    4. Quote via the pure pricing.compute_quote, tag tenant identity, author a
       one-line narrative.
    """
    adapters = get_adapters()

    book = await adapters.polymarket.get_orderbook(market_id, depth=10)
    if not book.bids or not book.asks:
        return None

    mid = book.microprice
    # max_spread is the venue's available spread budget in probability units;
    # floor it at MIN_SPREAD so a momentarily-locked book still quotes.
    max_spread = max(book.spread_bps / 10000, pricing.MIN_SPREAD)

    # Inventory ratio — neutral until the live inventory read is wired.
    inv_ratio = params.inventory_target_pct

    quote = pricing.compute_quote(mid, max_spread, inv_ratio, params)

    offset = params.quote_spread_bps_offset_to_max_spread
    target = params.inventory_target_pct
    narrative = (
        f"Quoting {market_id[:10]}…: bid {quote['bid']:.3f}/ask {quote['ask']:.3f} "
        f"at {offset * 100:.0f}% of max-spread; inv {inv_ratio:.0%} vs target {target:.0%}"
    )

    rationale = {
        "midpoint": mid,
        "max_spread": max_spread,
        "spread_offset": offset,
        "inventory_ratio": inv_ratio,
        "inventory_target": target,
        "user_id": inst["user_id"],
        "agent_instance_id": inst.get("id"),
    }

    return PricingDecision(
        decision_id=_next_id(),
        nonce=int(time.time() * 1_000_000) % 2**31,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash(rationale),
        user_id=inst["user_id"],
        agent_instance_id=inst.get("id"),
        market_id=market_id,
        market_question=await adapters.polymarket.get_market_question(market_id),
        bid=quote["bid"],
        ask=quote["ask"],
        size=quote["size"],
        confidence=quote["confidence"],
        appetite_profile=APPETITE,
        narrative=narrative,
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


async def _quote_instance(inst: dict) -> None:
    """Quote every eligible market for one tenant instance."""
    if inst.get("kill_switch"):
        log.info("Instance %s kill_switch on — skipping", inst.get("id"))
        return

    try:
        params = validate_params("nomos", inst.get("params") or {})
    except Exception as e:  # invalid stored params should not stall the loop
        log.warning("Instance %s has invalid params (%s) — skipping", inst.get("id"), e)
        return

    markets = _instance_markets(inst)
    for market_id in markets:
        # Whitelist gate. We do not have live per-market tags from the book yet,
        # so apply the operator's configured tags as the market's tags — a market
        # the operator subscribed inherits the operator's whitelist. This keeps
        # the gate active (fail-closed on an empty whitelist) without inventing a
        # tag feed.
        market_tags = params.market_whitelist_tags
        if not pricing.market_allowed(market_tags, params.market_whitelist_tags):
            continue

        # Per-market breaker. Fill-reconciliation (PnL per market) is deferred —
        # it will feed market_loss here. Until then pass 0.0 so the breaker is
        # wired but never trips spuriously.
        market_loss = 0.0
        if pricing.per_market_breaker_tripped(market_loss, params.daily_loss_limit_usd):
            log.info("Instance %s market %s breaker tripped — skipping",
                     inst.get("id"), market_id[:10])
            continue

        try:
            decision = await compute_quote(market_id, params, inst)
            if decision is not None:
                await submit(decision)
        except Exception as e:
            log.exception("compute_quote/submit failed for %s: %s", market_id[:10], e)


async def main() -> None:
    log.info("NOMOS starting — multi-tenant pricing loop, appetite=%s", APPETITE.value)

    while True:
        instances = await fetch_instances()
        total_markets = sum(len(_instance_markets(i)) for i in instances)
        if total_markets == 0:
            log.warning(
                "NOMOS idle — no markets to quote across %d instance(s). Set "
                "SUBSCRIBED_MARKETS to a comma-separated list of bytes32 market "
                "IDs (or register user instances with markets) to start quoting.",
                len(instances),
            )
            await asyncio.sleep(QUOTE_INTERVAL)
            continue

        for inst in instances:
            try:
                await _quote_instance(inst)
            except Exception as e:
                log.exception("instance %s loop failed: %s", inst.get("id"), e)
            # Spread the work across the interval so we re-quote roughly once
            # per QUOTE_INTERVAL regardless of how many markets are live.
            await asyncio.sleep(QUOTE_INTERVAL / max(total_markets, 1))


if __name__ == "__main__":
    asyncio.run(main())

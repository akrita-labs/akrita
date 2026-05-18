"""
Demo router.

POST /demo/run — fire the canonical 30-second demo loop:
  1. NOMOS submits a quote
  2. Polymarket fills it (mock)
  3. SPATHA fires a hedge against the resulting exposure
  4. AGROS rebalances USDC -> USYC
  5. Each step's trace is committed to Arc

This is what the judge sees on demo day. In the real demo, decisions
come from the live agents running on intervals — this endpoint just
forces the flow to happen on-demand so the dashboard is never empty.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter

from adapters import get_adapters
from orchestrator.app.routers.decisions import (
    post_hedge_decision,
    post_pricing_decision,
    post_treasury_decision,
)
from orchestrator.app.state import state
from shared.canonical import trace_hash
from shared.models import (
    AppetiteProfile,
    HedgeDecision,
    HedgeSide,
    HedgeVenue,
    MarginAsset,
    PricingDecision,
    TreasuryAction,
    TreasuryDecision,
)

router = APIRouter()
log = logging.getLogger("akrita.demo")

MARKET_ID = "0x" + "a" * 40  # one of the canned mock markets


@router.post("/run")
async def run_demo() -> dict:
    """Execute the canonical 30-second demo flow."""
    adapters = get_adapters()
    log.info("=== AKRITA demo flow starting ===")
    timeline = []

    # 1. NOMOS quote
    book = await adapters.polymarket.get_orderbook(MARKET_ID)
    mid = book.microprice
    pricing = PricingDecision(
        decision_id=await state.next_decision_id("nomos"),
        nonce=int(time.time() * 1000) % 10_000_000,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash({"step": "demo_pricing", "ts": time.time()}),
        market_id=MARKET_ID,
        market_question="Will the Fed cut rates by 25bps at June FOMC?",
        bid=round(max(0.05, mid - 0.015), 4),
        ask=round(min(0.95, mid + 0.015), 4),
        size=100.0,
        confidence=0.74,
        appetite_profile=AppetiteProfile.BALANCED,
    )
    pricing_result = await post_pricing_decision(pricing)
    timeline.append({"step": 1, "agent": "NOMOS", "result": pricing_result})
    log.info("Step 1: NOMOS quote submitted (trace=%s)",
             pricing_result.get("trace_hash", "")[:14])
    await asyncio.sleep(2.0)

    # 2. Force a fill (the mock has stochastic fills; we drive one directly)
    # We don't have a public "force fill" endpoint, so we record a fill into state.
    fill_price = pricing.bid
    fill_size = pricing.size
    fee = fill_size * fill_price * 0.005
    await state.record_fill({
        "market_id": MARKET_ID,
        "side": "BUY",
        "price": fill_price,
        "size": fill_size,
        "builder_fee_usdc": fee,
        "polygon_tx": "0xfilltx" + "f" * 56,
        "ts_ms": int(time.time() * 1000),
    })
    await state.broadcast({
        "type": "fill",
        "market_id": MARKET_ID,
        "side": "BUY",
        "price": fill_price,
        "size": fill_size,
        "builder_fee_usdc": fee,
        "ts_ms": int(time.time() * 1000),
    })
    timeline.append({"step": 2, "event": "OrderFilled", "builder_fee_usdc": fee})
    log.info("Step 2: OrderFilled, builder_fee=$%.4f", fee)
    await asyncio.sleep(1.5)

    # 3. SPATHA hedge — we now have net long inventory; short BTC perp as proxy
    hedge = HedgeDecision(
        decision_id=await state.next_decision_id("spatha"),
        nonce=int(time.time() * 1000) % 10_000_000 + 1,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash({"step": "demo_hedge", "ts": time.time()}),
        market_id=MARKET_ID,
        action="open",
        venue=HedgeVenue.HYPERLIQUID,
        instrument="BTC-PERP",
        side=HedgeSide.SHORT,
        size=0.05,
        leverage=2.0,
        margin_asset=MarginAsset.USDC,
        margin_amount=250.0,
        stop_loss=110_000.0,
    )
    hedge_result = await post_hedge_decision(hedge)
    timeline.append({"step": 3, "agent": "SPATHA", "result": hedge_result})
    log.info("Step 3: SPATHA hedge open (trace=%s)",
             hedge_result.get("trace_hash", "")[:14])
    await asyncio.sleep(1.5)

    # 4. AGROS sweep surplus USDC into USYC
    treasury = TreasuryDecision(
        decision_id=await state.next_decision_id("agros"),
        nonce=int(time.time() * 1000) % 10_000_000 + 2,
        ts_ms=int(time.time() * 1000),
        rationale_hash=trace_hash({"step": "demo_treasury", "ts": time.time()}),
        action=TreasuryAction.USYC_SUBSCRIBE,
        amount=500.0,
        projected_outflow_60min=100.0,
        safety_multiplier=1.5,
    )
    treasury_result = await post_treasury_decision(treasury)
    timeline.append({"step": 4, "agent": "AGROS", "result": treasury_result})
    log.info("Step 4: AGROS USYC subscribe (trace=%s)",
             treasury_result.get("trace_hash", "")[:14])

    log.info("=== AKRITA demo flow complete ===")
    return {
        "demo_run_ts_ms": int(time.time() * 1000),
        "steps": timeline,
        "cumulative_builder_fees_usdc": await state.cumulative_builder_fees_usdc(),
    }

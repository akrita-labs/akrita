"""
POST /decisions/{role}  — agent submits a structured decision.

Lifecycle for each incoming decision:
  1. Pydantic schema validation (FastAPI built-in)
  2. Nonce replay check
  3. Risk Agent gate (12 deterministic checks)
  4. Build trace body (fundamentals/technical/conclusion)
  5. Pin trace to IPFS via Nanopayment
  6. Commit trace hash to TraceRegistry on Arc
  7. Execute the decision (Polymarket / Hyperliquid / USYC / Gateway)
  8. Persist + broadcast to UI
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException

from adapters import get_adapters
from orchestrator.app.config import settings
from orchestrator.app.risk_agent import RiskAgent
from orchestrator.app.state import state
from orchestrator.app.trace_pipeline import TracePipeline
from shared.models import (
    HedgeDecision,
    PricingDecision,
    TreasuryAction,
    TreasuryDecision,
)

router = APIRouter()
log = logging.getLogger("akrita.decisions")

risk_agent = RiskAgent()
trace_pipeline = TracePipeline(trace_registry_addr=settings.trace_registry_addr)


# ---------------------------------------------------------------------------
# Pricing (NOMOS)
# ---------------------------------------------------------------------------

@router.post("/pricing")
async def post_pricing_decision(decision: PricingDecision) -> dict:
    return await _process(decision, _execute_pricing, _build_pricing_trace_sections)


async def _execute_pricing(decision: PricingDecision) -> dict:
    """Submit the quote to Polymarket V2 via py-clob-client (mocked in dev)."""
    adapters = get_adapters()
    bid_id, ask_id = await adapters.polymarket.submit_quote(
        market_id=decision.market_id,
        bid=decision.bid,
        ask=decision.ask,
        size=decision.size,
        builder_code=settings.builder_code,
    )
    return {"bid_order_id": bid_id, "ask_order_id": ask_id}


async def _build_pricing_trace_sections(decision: PricingDecision) -> tuple[dict, dict, dict]:
    adapters = get_adapters()
    book = await adapters.polymarket.get_orderbook(decision.market_id, depth=5)
    question = await adapters.polymarket.get_market_question(decision.market_id)
    recent = await adapters.polymarket.get_recent_fills(decision.market_id, n=10)

    fundamentals = {
        "market_id": decision.market_id,
        "market_question": question,
        "current_implied_probability": (book.best_bid + book.best_ask) / 2,
    }
    technical = {
        "orderbook_state": {
            "best_bid": book.best_bid,
            "best_ask": book.best_ask,
            "spread_bps": book.spread_bps,
            "microprice": book.microprice,
        },
        "recent_fills": [
            {"price": f.price, "size": f.size, "ts": f.ts_ms}
            for f in recent[:5]
        ],
        "operator_fee_inferred_bps": decision.operator_fee_bps,
    }
    conclusion = {
        "final_bid": decision.bid,
        "final_ask": decision.ask,
        "size": decision.size,
        "confidence": decision.confidence,
        "appetite": decision.appetite_profile,
    }
    return fundamentals, technical, conclusion


# ---------------------------------------------------------------------------
# Hedge (SPATHA)
# ---------------------------------------------------------------------------

@router.post("/hedge")
async def post_hedge_decision(decision: HedgeDecision) -> dict:
    return await _process(decision, _execute_hedge, _build_hedge_trace_sections)


async def _execute_hedge(decision: HedgeDecision) -> dict:
    adapters = get_adapters()
    if decision.action == "open":
        pos = await adapters.hyperliquid.open_position(
            instrument=decision.instrument,
            side=decision.side,
            size=decision.size,
            margin_amount=decision.margin_amount,
            leverage=decision.leverage,
            stop_loss=decision.stop_loss,
        )
        await state.record_hedge({
            "position_id": pos.position_id,
            "venue": pos.venue,
            "instrument": pos.instrument,
            "side": pos.side,
            "size": pos.size,
            "entry_price": pos.entry_price,
            "margin_asset": pos.margin_asset,
            "margin_amount": pos.margin_amount,
            "status": pos.status,
            "pnl_usdc": pos.pnl_usdc,
            "ts_ms": int(time.time() * 1000),
        })
        return {"position_id": pos.position_id, "entry_price": pos.entry_price}

    elif decision.action == "close":
        if decision.closes_position_id is None:
            raise HTTPException(400, "closes_position_id required when action=close")
        pos = await adapters.hyperliquid.close_position(decision.closes_position_id)
        await state.record_hedge({
            "position_id": pos.position_id,
            "status": pos.status,
            "pnl_usdc": pos.pnl_usdc,
            "ts_ms": int(time.time() * 1000),
        })
        return {"position_id": pos.position_id, "pnl_usdc": pos.pnl_usdc}
    else:
        raise HTTPException(400, f"unknown hedge action {decision.action}")


async def _build_hedge_trace_sections(decision: HedgeDecision) -> tuple[dict, dict, dict]:
    adapters = get_adapters()
    inv = await state.get_inventory(decision.market_id)
    funding = await adapters.hyperliquid.get_funding_rate(decision.instrument)

    fundamentals = {
        "underlying_market_id": decision.market_id,
        "instrument": decision.instrument,
        "venue": decision.venue,
        "current_inventory_exposure": inv.net_exposure,
    }
    technical = {
        "funding_rate_8h": funding,
        "hedge_side": decision.side,
        "hedge_size": decision.size,
        "margin_asset": decision.margin_asset,
        "leverage": decision.leverage,
    }
    conclusion = {
        "action": decision.action,
        "margin_amount": decision.margin_amount,
        "stop_loss": decision.stop_loss,
        "closes_position_id": decision.closes_position_id,
    }
    return fundamentals, technical, conclusion


# ---------------------------------------------------------------------------
# Treasury (AGROS)
# ---------------------------------------------------------------------------

@router.post("/treasury")
async def post_treasury_decision(decision: TreasuryDecision) -> dict:
    return await _process(decision, _execute_treasury, _build_treasury_trace_sections)


async def _execute_treasury(decision: TreasuryDecision) -> dict:
    adapters = get_adapters()
    action = decision.action

    if action == TreasuryAction.NOOP.value:
        return {"action": "noop"}

    if action == TreasuryAction.USYC_SUBSCRIBE.value:
        receipt = await adapters.usyc.subscribe("agros-keeper", decision.amount)
        await state.record_treasury({
            "action": action,
            "usdc_amount": receipt.usdc_in,
            "usyc_amount": receipt.usyc_out,
            "nav": receipt.nav,
            "tx_hash": receipt.tx_hash,
            "ts_ms": int(time.time() * 1000),
        })
        return {"tx_hash": receipt.tx_hash, "usyc_out": receipt.usyc_out, "nav": receipt.nav}

    if action == TreasuryAction.USYC_REDEEM.value:
        receipt = await adapters.usyc.redeem("agros-keeper", decision.amount)
        await state.record_treasury({
            "action": action,
            "usyc_amount": receipt.usyc_in,
            "usdc_amount": receipt.usdc_out,
            "fee_paid": receipt.fee,
            "tx_hash": receipt.tx_hash,
            "ts_ms": int(time.time() * 1000),
        })
        return {"tx_hash": receipt.tx_hash, "usdc_out": receipt.usdc_out, "fee": receipt.fee}

    if action == TreasuryAction.GATEWAY_TRANSFER.value:
        receipt = await adapters.gateway.transfer(
            wallet_id="agros-keeper",
            amount_usdc=decision.amount,
            src_chain=decision.src_chain,
            dst_chain=decision.dst_chain,
        )
        await state.record_treasury({
            "action": action,
            "usdc_amount": receipt.amount_usdc,
            "src_chain": receipt.src_chain,
            "dst_chain": receipt.dst_chain,
            "src_tx": receipt.src_tx,
            "dst_tx": receipt.dst_tx,
            "elapsed_ms": receipt.elapsed_ms,
            "ts_ms": int(time.time() * 1000),
        })
        return {"elapsed_ms": receipt.elapsed_ms, "src_tx": receipt.src_tx, "dst_tx": receipt.dst_tx}

    raise HTTPException(400, f"unknown treasury action {action}")


async def _build_treasury_trace_sections(decision: TreasuryDecision) -> tuple[dict, dict, dict]:
    adapters = get_adapters()
    nav = await adapters.usyc.get_nav_per_share()
    apy = await adapters.usyc.get_current_yield_apy()
    bal = await adapters.wallets.get_balance("agros-keeper", "arc")

    fundamentals = {
        "usyc_nav_per_share": nav,
        "usyc_apy": apy,
        "agros_arc_balance": bal,
    }
    technical = {
        "projected_outflow_60min": decision.projected_outflow_60min,
        "safety_multiplier": decision.safety_multiplier,
        "src_chain": decision.src_chain,
        "dst_chain": decision.dst_chain,
    }
    conclusion = {
        "action": decision.action,
        "amount": decision.amount,
    }
    return fundamentals, technical, conclusion


# ---------------------------------------------------------------------------
# Generic decision processing
# ---------------------------------------------------------------------------

async def _process(decision, executor, trace_builder) -> dict:
    """Run the full lifecycle on any decision type."""
    # 1. Nonce replay check
    if not await state.claim_nonce(decision.agent_role, decision.nonce):
        raise HTTPException(409, "Nonce already used")

    # 2. Risk gate
    risk_result = risk_agent.evaluate(decision, context={"now_ms": int(time.time() * 1000)})
    if not risk_result.approved:
        log.warning("Decision %d rejected by risk gate: %s",
                    decision.decision_id, risk_result.reason)
        await state.store_decision({**decision.model_dump(mode="json"),
                                    "risk_passed": False,
                                    "risk_reason": risk_result.reason})
        return {
            "status": "rejected",
            "reason": risk_result.reason,
            "checks": [c.model_dump(mode="json") for c in risk_result.checks],
        }

    # 3. Build trace body
    fundamentals, technical, conclusion = await trace_builder(decision)

    # 4. Pin + commit trace
    try:
        commit = await trace_pipeline.commit(
            decision, risk_result, fundamentals, technical, conclusion,
        )
    except Exception as e:
        log.exception("Trace pipeline failed for decision %d", decision.decision_id)
        raise HTTPException(500, f"trace pipeline failed: {e}")

    await state.store_trace(decision.decision_id, {
        "decision_id": commit.decision_id,
        "agent_role": commit.agent_role,
        "trace_hash": commit.trace_hash,
        "ipfs_cid": commit.ipfs_cid,
        "arc_tx_hash": commit.arc_tx_hash,
        "arc_block": commit.arc_block,
        "body_size_bytes": commit.body_size_bytes,
        "ts_ms": int(time.time() * 1000),
    })

    # 5. Execute the actual on-chain action
    try:
        exec_result = await executor(decision)
    except Exception as e:
        log.exception("Execution failed for decision %d", decision.decision_id)
        raise HTTPException(500, f"execution failed: {e}")

    # 6. Persist decision + broadcast
    await state.store_decision({
        **decision.model_dump(mode="json"),
        "risk_passed": True,
        "trace_hash": commit.trace_hash,
        "ipfs_cid": commit.ipfs_cid,
        "arc_tx_hash": commit.arc_tx_hash,
        "exec_result": exec_result,
    })
    await state.broadcast({
        "type": "decision",
        "decision_id": decision.decision_id,
        "agent": decision.agent_role,
        "trace_hash": commit.trace_hash,
        "arc_tx_hash": commit.arc_tx_hash,
        "exec_result": exec_result,
        "ts_ms": int(time.time() * 1000),
    })

    return {
        "status": "submitted",
        "decision_id": decision.decision_id,
        "trace_hash": commit.trace_hash,
        "ipfs_cid": commit.ipfs_cid,
        "arc_tx_hash": commit.arc_tx_hash,
        "arc_block": commit.arc_block,
        "exec_result": exec_result,
    }

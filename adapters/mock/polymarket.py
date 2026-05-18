"""
Mock Polymarket V2 adapter.

Generates realistic orderbook snapshots, fills events, and accepts
quote submissions. State is in-memory; resets on restart.

Use this until py-clob-client-v2 integration is wired up. The protocol
interface is the same, so swapping later is just an import change.
"""
from __future__ import annotations

import asyncio
import random
import time

from adapters.base import (
    Fill,
    Orderbook,
    OrderbookLevel,
    PolymarketAdapter,
)


# A handful of canned mock markets that look like real Polymarket questions
MOCK_MARKETS = {
    "0x" + "a" * 40: {
        "question": "Will the Fed cut rates by 25bps at June FOMC?",
        "fair_value": 0.62,
        "volatility": 0.04,
    },
    "0x" + "b" * 40: {
        "question": "Will BTC close above $120K on May 31, 2026?",
        "fair_value": 0.41,
        "volatility": 0.06,
    },
    "0x" + "c" * 40: {
        "question": "Will the ECB hold rates at the next meeting?",
        "fair_value": 0.78,
        "volatility": 0.03,
    },
    "0x" + "d" * 40: {
        "question": "Will US CPI YoY come in above 3.5% for May?",
        "fair_value": 0.34,
        "volatility": 0.05,
    },
    "0x" + "e" * 40: {
        "question": "Will ETH/BTC ratio exceed 0.06 by month end?",
        "fair_value": 0.55,
        "volatility": 0.04,
    },
}


class MockPolymarket(PolymarketAdapter):
    def __init__(self, fill_probability_per_quote: float = 0.15):
        self._fill_probability = fill_probability_per_quote
        self._fills: list[Fill] = []
        self._open_orders: dict[str, dict] = {}
        self._next_order_id = 1000
        self._builder_fee_bps = 50  # 0.5% builder fee for mock
        self._next_tx_seq = 1

    async def get_orderbook(self, market_id: str, depth: int = 10) -> Orderbook:
        if market_id not in MOCK_MARKETS:
            # Generate orderbook anyway with neutral midpoint
            fair = 0.5
            vol = 0.04
        else:
            mkt = MOCK_MARKETS[market_id]
            fair = mkt["fair_value"]
            vol = mkt["volatility"]

        # Wander the midpoint slightly to simulate live market motion
        midpoint = fair + random.uniform(-vol / 4, vol / 4)
        spread = 0.015 + random.uniform(0, 0.02)

        bids = []
        asks = []
        for i in range(depth):
            tick = 0.005 * (i + 1)
            bids.append(OrderbookLevel(
                price=max(0.01, midpoint - spread / 2 - tick),
                size=round(random.uniform(50, 500), 2),
            ))
            asks.append(OrderbookLevel(
                price=min(0.99, midpoint + spread / 2 + tick),
                size=round(random.uniform(50, 500), 2),
            ))

        return Orderbook(
            market_id=market_id,
            bids=bids,
            asks=asks,
            ts_ms=int(time.time() * 1000),
        )

    async def get_recent_fills(self, market_id: str, n: int = 50) -> list[Fill]:
        # Filter our internal fills log to this market
        market_fills = [f for f in self._fills if f.market_id == market_id]
        return market_fills[-n:]

    async def submit_quote(
        self,
        market_id: str,
        bid: float,
        ask: float,
        size: float,
        builder_code: str,
    ) -> tuple[str, str]:
        # Generate two order IDs (bid + ask)
        bid_id = f"mock-order-{self._next_order_id}"
        self._next_order_id += 1
        ask_id = f"mock-order-{self._next_order_id}"
        self._next_order_id += 1

        self._open_orders[bid_id] = {
            "market_id": market_id, "side": "BUY", "price": bid,
            "size": size, "builder": builder_code, "ts": time.time(),
        }
        self._open_orders[ask_id] = {
            "market_id": market_id, "side": "SELL", "price": ask,
            "size": size, "builder": builder_code, "ts": time.time(),
        }

        # Probabilistically simulate a fill arriving moments later
        if random.random() < self._fill_probability:
            asyncio.create_task(self._simulate_fill(bid_id, ask_id, market_id,
                                                    bid, ask, size, builder_code))

        return bid_id, ask_id

    async def _simulate_fill(self, bid_id, ask_id, market_id, bid, ask, size, builder_code):
        await asyncio.sleep(random.uniform(0.3, 2.0))
        # Randomly fill either bid or ask side
        if random.random() < 0.5 and bid_id in self._open_orders:
            self._open_orders.pop(bid_id)
            side = "BUY"
            price = bid
        elif ask_id in self._open_orders:
            self._open_orders.pop(ask_id)
            side = "SELL"
            price = ask
        else:
            return

        fee = size * price * (self._builder_fee_bps / 10000)
        tx_hash = f"0xmocktx{self._next_tx_seq:062x}"
        self._next_tx_seq += 1

        self._fills.append(Fill(
            market_id=market_id,
            price=price,
            size=size,
            side=side,
            builder_fee_usdc=fee,
            ts_ms=int(time.time() * 1000),
            tx_hash=tx_hash,
        ))

    async def cancel_order(self, order_id: str) -> bool:
        return self._open_orders.pop(order_id, None) is not None

    async def get_attributed_fills_since(self, since_ts_ms: int) -> list[Fill]:
        return [f for f in self._fills if f.ts_ms >= since_ts_ms]

    async def get_market_question(self, market_id: str) -> str:
        if market_id in MOCK_MARKETS:
            return MOCK_MARKETS[market_id]["question"]
        return f"Unknown market {market_id}"

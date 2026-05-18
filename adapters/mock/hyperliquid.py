"""
Mock Hyperliquid adapter for hedge legs.

Simulates open/close perp positions, funding rates, and mark prices.
Position state is in-memory; resets on restart.
"""
from __future__ import annotations

import random
from typing import Optional

from adapters.base import HedgePosition, HyperliquidAdapter


class MockHyperliquid(HyperliquidAdapter):
    def __init__(self):
        self._positions: dict[int, HedgePosition] = {}
        self._next_position_id = 5000
        self._instrument_prices: dict[str, float] = {
            "BTC-PERP": 105_000.0,
            "ETH-PERP": 3_800.0,
            "SOL-PERP": 175.0,
        }
        self._funding_rates: dict[str, float] = {
            "BTC-PERP": 0.0001,   # 0.01% per 8h
            "ETH-PERP": 0.00012,
            "SOL-PERP": 0.00015,
        }

    async def open_position(
        self,
        instrument: str,
        side: str,
        size: float,
        margin_amount: float,
        leverage: float = 1.0,
        stop_loss: Optional[float] = None,
    ) -> HedgePosition:
        entry_price = self._instrument_prices.get(instrument, 100.0)
        # Add light slippage
        slip = entry_price * random.uniform(0.0002, 0.0015)
        entry_price = entry_price + slip if side == "long" else entry_price - slip

        position_id = self._next_position_id
        self._next_position_id += 1

        pos = HedgePosition(
            position_id=position_id,
            venue="hyperliquid",
            instrument=instrument,
            side=side,
            size=size,
            entry_price=entry_price,
            margin_asset="USDC",
            margin_amount=margin_amount,
            status="open",
        )
        self._positions[position_id] = pos
        return pos

    async def close_position(self, position_id: int) -> HedgePosition:
        pos = self._positions.get(position_id)
        if not pos:
            raise ValueError(f"Position {position_id} not found")
        if pos.status != "open":
            return pos
        # Compute PnL based on simulated current price
        cur = self._instrument_prices.get(pos.instrument, pos.entry_price)
        cur = cur * random.uniform(0.998, 1.002)  # tiny noise
        diff = cur - pos.entry_price
        pos.pnl_usdc = diff * pos.size if pos.side == "long" else -diff * pos.size
        pos.status = "closed"
        return pos

    async def get_position(self, position_id: int) -> HedgePosition:
        pos = self._positions.get(position_id)
        if not pos:
            raise ValueError(f"Position {position_id} not found")
        return pos

    async def get_open_positions(self) -> list[HedgePosition]:
        return [p for p in self._positions.values() if p.status == "open"]

    async def get_funding_rate(self, instrument: str) -> float:
        return self._funding_rates.get(instrument, 0.0001)

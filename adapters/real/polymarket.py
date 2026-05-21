"""
PolymarketReal — Polymarket V2 CLOB integration.

Split by capability:

  READS (no signing, public REST) — fully live:
    - get_orderbook: resolve condition_id -> Yes token -> /book, ordered so
      bids[0] is the best (highest) bid and asks[0] the best (lowest) ask.
    - get_market_question, get_recent_fills, last trade price.

  WRITES (signed orders) — structured, gated on collateral:
    - submit_quote / cancel_order go through py-clob-client with the V2
      BuilderConfig that attaches our bytes32 builder code (the thing that
      earns attribution fees). Polymarket signs orders with a LOCAL EOA key;
      our keeper wallets are Circle MPC (no extractable key), so the trading
      EOA is a dedicated signer (secrets/polymarket_signer.json) that holds
      pUSD collateral. Builder attribution is independent of which wallet
      signs, so fees still accrue to our registered builder code.

  Live order submission additionally requires:
    1. The signer EOA funded with pUSD collateral (wrap USDC at the V2
       Collateral Onramp).
    2. CTF/exchange allowances approved for that EOA.
  Until both are in place, submit_quote raises a clear, actionable error.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from adapters.base import Fill, Orderbook, OrderbookLevel
from shared.config import settings


CLOB_BASE = settings.poly_relayer_url or "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137


def _norm_condition_id(market_id: str) -> str:
    """NOMOS market_id is a condition_id (0x + 64 hex). Pass through."""
    return market_id


class PolymarketReal:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=CLOB_BASE,
            timeout=15.0,
            headers={"User-Agent": "akrita-nomos/0.1", "Accept": "application/json"},
        )
        # condition_id -> {"question": str, "tokens": [{token_id, outcome}], "tick_size": float}
        self._market_cache: dict[str, dict] = {}
        self._client = None  # lazily-built py-clob-client for writes

    # ----- market metadata -------------------------------------------------

    async def _market_meta(self, condition_id: str) -> dict:
        if condition_id in self._market_cache:
            return self._market_cache[condition_id]
        resp = await self._http.get(f"/markets/{condition_id}")
        resp.raise_for_status()
        m = resp.json()
        meta = {
            "question": m.get("question", ""),
            "tokens": m.get("tokens", []),
            "tick_size": float(m.get("minimum_tick_size", 0.01) or 0.01),
            "neg_risk": bool(m.get("neg_risk", False)),
        }
        self._market_cache[condition_id] = meta
        return meta

    async def _yes_token_id(self, condition_id: str) -> str:
        meta = await self._market_meta(condition_id)
        toks = meta["tokens"]
        if not toks:
            raise ValueError(f"market {condition_id} has no tradeable tokens")
        for t in toks:
            if str(t.get("outcome", "")).lower() in ("yes", "up", "over"):
                return t["token_id"]
        return toks[0]["token_id"]

    # ----- reads -----------------------------------------------------------

    async def get_orderbook(self, market_id: str, depth: int = 10) -> Orderbook:
        condition_id = _norm_condition_id(market_id)
        token_id = await self._yes_token_id(condition_id)
        resp = await self._http.get("/book", params={"token_id": token_id})
        resp.raise_for_status()
        book = resp.json()

        # Polymarket returns bids ascending and asks descending by price.
        # Order so index 0 is the best price on each side.
        bids = sorted(
            (OrderbookLevel(price=float(b["price"]), size=float(b["size"])) for b in book.get("bids", [])),
            key=lambda lvl: lvl.price,
            reverse=True,
        )[:depth]
        asks = sorted(
            (OrderbookLevel(price=float(a["price"]), size=float(a["size"])) for a in book.get("asks", [])),
            key=lambda lvl: lvl.price,
        )[:depth]
        ts_ms = int(book.get("timestamp") or time.time() * 1000)
        return Orderbook(market_id=market_id, bids=bids, asks=asks, ts_ms=ts_ms)

    async def get_market_question(self, market_id: str) -> str:
        meta = await self._market_meta(_norm_condition_id(market_id))
        return meta["question"]

    async def get_recent_fills(self, market_id: str, n: int = 50) -> list[Fill]:
        """Public trade history via the data API. Degrades to [] if unavailable
        (the trace pipeline tolerates an empty recent-fills section)."""
        condition_id = _norm_condition_id(market_id)
        try:
            async with httpx.AsyncClient(timeout=12.0, headers={"User-Agent": "akrita"}) as client:
                resp = await client.get(
                    "https://data-api.polymarket.com/trades",
                    params={"market": condition_id, "limit": n},
                )
                if resp.status_code != 200:
                    return []
                trades = resp.json()
        except httpx.RequestError:
            return []

        out: list[Fill] = []
        for t in trades if isinstance(trades, list) else []:
            try:
                out.append(
                    Fill(
                        market_id=market_id,
                        price=float(t.get("price", 0)),
                        size=float(t.get("size", 0)),
                        side=str(t.get("side", "")).upper(),
                        builder_fee_usdc=0.0,
                        ts_ms=int(float(t.get("timestamp", 0)) * 1000) if t.get("timestamp") else 0,
                        tx_hash=t.get("transactionHash", "") or "",
                    )
                )
            except (TypeError, ValueError):
                continue
        return out[:n]

    async def get_attributed_fills_since(self, since_ts_ms: int) -> list[Fill]:
        """Builder-attributed fills. Requires L2 auth + builder creds; wired
        with the authenticated user stream in the WS subscriber. Returns []
        until order submission is live."""
        return []

    # ----- writes (gated on pUSD collateral + signer EOA) ------------------

    def _require_writes_ready(self) -> None:
        if not settings.poly_builder_code:
            raise RuntimeError("POLY_BUILDER_CODE not set — refusing to submit unattributed orders")
        if not (settings.poly_api_key and settings.poly_api_secret and settings.poly_api_passphrase):
            raise RuntimeError("Polymarket V2 API creds (key/secret/passphrase) not set")
        signer = Path(__file__).resolve().parents[2] / "secrets" / "polymarket_signer.json"
        if not signer.exists():
            raise RuntimeError(
                "Polymarket signing EOA not provisioned. Run the PR 3 bootstrap to "
                "generate secrets/polymarket_signer.json. See docs/POLYMARKET_LIVE.md."
            )
        if not settings.poly_collateral_ready:
            raise RuntimeError(
                "Polymarket collateral not ready. The signer EOA "
                f"({json.loads(signer.read_text())['address']}) must hold pUSD collateral "
                "(wrap USDC at the V2 Collateral Onramp) with CTF/exchange allowances "
                "approved, then set POLY_COLLATERAL_READY=1. See docs/POLYMARKET_LIVE.md."
            )

    def _get_client(self):
        if self._client is not None:
            return self._client
        self._require_writes_ready()
        from py_builder_signing_sdk.config import BuilderConfig
        from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        signer = json.loads(
            (Path(__file__).resolve().parents[2] / "secrets" / "polymarket_signer.json").read_text()
        )
        builder_cfg = BuilderConfig(
            local_builder_creds=BuilderApiKeyCreds(
                key=settings.poly_api_key,
                secret=settings.poly_api_secret,
                passphrase=settings.poly_api_passphrase,
            )
        )
        self._client = ClobClient(
            host=CLOB_BASE,
            chain_id=POLYGON_CHAIN_ID,
            key=signer["privateKey"],
            creds=ApiCreds(
                api_key=settings.poly_api_key,
                api_secret=settings.poly_api_secret,
                api_passphrase=settings.poly_api_passphrase,
            ),
            builder_config=builder_cfg,
        )
        return self._client

    async def submit_quote(
        self,
        market_id: str,
        bid: float,
        ask: float,
        size: float,
        builder_code: str,
    ) -> tuple[str, str]:
        """Submit a bid + ask, both carrying the builder code. Returns
        (bid_order_id, ask_order_id)."""
        import asyncio

        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL

        client = self._get_client()
        token_id = await self._yes_token_id(_norm_condition_id(market_id))

        def _place(side: str, price: float) -> str:
            order = client.create_order(OrderArgs(token_id=token_id, price=price, size=size, side=side))
            resp = client.post_order(order, OrderType.GTC)
            return resp.get("orderID") or resp.get("orderId") or ""

        bid_id = await asyncio.to_thread(_place, BUY, bid)
        ask_id = await asyncio.to_thread(_place, SELL, ask)
        return bid_id, ask_id

    async def cancel_order(self, order_id: str) -> bool:
        import asyncio

        client = self._get_client()
        resp = await asyncio.to_thread(client.cancel_orders, [order_id])
        return bool(resp)

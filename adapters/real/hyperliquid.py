"""
HyperliquidReal — Hyperliquid testnet perp venue for hedge legs.

Split by capability (mirrors the read/write split in ArcReal and
PolymarketReal):

  READS (no margin required, public + user-scoped query API) — fully live:
    - get_funding_rate: current hourly funding for a coin (meta_and_asset_ctxs).
    - get_position / get_open_positions: the master account's perp positions.
    - account_value / withdrawable: read straight off user_state.
  These work regardless of whether the account holds any USDC margin, so we
  exercise them live in the smoke script + tests.

  WRITES (signed orders) — structured, gated on a funded account:
    - open_position / close_position go through the SDK's Exchange, which
      signs with a RAW local key (eth_account LocalAccount) — NOT Circle MPC.
      Hyperliquid runs its own non-EVM L1, so there is no Circle wallet there;
      the API wallet keystore (secrets/hl_api_wallet.json) is an *agent* wallet
      authorised to place orders ON BEHALF OF the master account.

  Live order submission additionally requires:
    1. The MASTER account funded with USDC margin (deposit at the HL bridge,
       app.hyperliquid-testnet.xyz). An early CCTP deposit landed on the wrong
       contract, so the account may read accountValue == 0.
  Until the account is funded, open_position raises a clear, actionable error
  rather than firing an order that would bounce for lack of margin.

SDK shape: the hyperliquid SDK is synchronous. As with CircleWalletsReal we
wrap every blocking call in `asyncio.to_thread` so the event loop keeps moving.

Position identity: the HedgePosition protocol keys positions by an int
`position_id`, but Hyperliquid keys perp positions by coin. We map a coin to
its stable HL asset index (Info.name_to_asset, e.g. BTC -> 3, ETH -> 4): the
index is deterministic and reversible, so close_position / get_position can
recover the coin from the id without any external state. We also remember the
coin for any id we hand out, so callers can round-trip ids we issued.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from eth_account import Account

from adapters.base import HedgePosition
from shared.config import settings


VENUE = "hyperliquid"

# Below this the master account has effectively no usable margin; refuse to
# open rather than submit an order that will obviously reject.
_MIN_ACCOUNT_VALUE_USDC = 1.0


def _coin_of(instrument: str) -> str:
    """Map a protocol instrument ("BTC-PERP", "ETH-PERP") to the bare HL coin
    the SDK expects ("BTC", "ETH"). Already-bare coins pass through."""
    return instrument.strip().upper().removesuffix("-PERP")


class HyperliquidReal:
    """Hyperliquid testnet perp client (hedge legs).

    Constructed eagerly (so `get_adapters()` returns a complete container):
    we load the API-wallet keystore and build the SDK's Info (reads) +
    Exchange (writes) clients. The write path is gated separately, at call
    time, on the master account actually holding margin.
    """

    def __init__(self) -> None:
        from hyperliquid.exchange import Exchange
        from hyperliquid.info import Info

        keyfile = Path(settings.hl_api_wallet_keyfile)
        if not keyfile.is_absolute():
            keyfile = Path(__file__).resolve().parents[2] / keyfile
        if not keyfile.exists():
            raise RuntimeError(
                f"Hyperliquid API-wallet keystore not found at {keyfile}. "
                "Expected JSON with 'address' and 'privateKey' (0x-prefixed)."
            )
        keystore = json.loads(keyfile.read_text())
        priv = keystore.get("privateKey")
        if not priv:
            raise RuntimeError(f"keystore {keyfile} missing 'privateKey'")
        if not settings.hl_account_addr:
            raise RuntimeError("HL_ACCOUNT_ADDR not set — cannot identify the master account")

        # The API wallet signs; the master account is the position owner. The
        # SDK routes orders for `account_address` when it differs from signer.
        self._master = settings.hl_account_addr
        self._signer: Account = Account.from_key(priv)
        base_url = settings.hl_url

        self._info = Info(base_url, skip_ws=True)
        self._exchange = Exchange(
            self._signer,
            base_url,
            account_address=self._master,
        )

    # ----- position id <-> coin mapping -----------------------------------

    def _id_for(self, coin: str) -> int:
        """Stable, reversible position id for a coin (its HL asset index)."""
        return int(self._info.name_to_asset(coin))

    def _coin_for(self, position_id: int) -> str:
        """Recover the coin for a position id issued by `_id_for`."""
        for coin, idx in self._info.coin_to_asset.items():
            if int(idx) == int(position_id):
                return coin
        raise KeyError(f"no Hyperliquid coin maps to position_id={position_id}")

    # ----- account state (reads — no margin required) ---------------------

    async def _user_state(self) -> dict:
        return await asyncio.to_thread(self._info.user_state, self._master)

    async def get_account_value(self) -> float:
        """USDC account value of the master account (0.0 if unfunded)."""
        st = await self._user_state()
        return float(st.get("marginSummary", {}).get("accountValue", 0.0) or 0.0)

    async def get_withdrawable(self) -> float:
        """Free (withdrawable) USDC margin on the master account."""
        st = await self._user_state()
        return float(st.get("withdrawable", 0.0) or 0.0)

    def _position_from_asset(self, ap: dict) -> HedgePosition:
        """Build a HedgePosition from one user_state assetPositions entry."""
        pos = ap.get("position", {})
        coin = pos.get("coin", "")
        szi = float(pos.get("szi", 0.0) or 0.0)  # signed: + long, - short
        entry = float(pos.get("entryPx") or 0.0)
        margin_used = float(pos.get("marginUsed") or 0.0)
        pnl = float(pos.get("unrealizedPnl") or 0.0)
        return HedgePosition(
            position_id=self._id_for(coin) if coin else 0,
            venue=VENUE,
            instrument=f"{coin}-PERP" if coin else "",
            side="long" if szi >= 0 else "short",
            size=abs(szi),
            entry_price=entry,
            margin_asset="USDC",
            margin_amount=margin_used,
            status="open",
            pnl_usdc=pnl,
        )

    # ----- reads -----------------------------------------------------------

    async def get_funding_rate(self, instrument: str) -> float:
        """Current (hourly) funding rate for the coin. Positive = longs pay
        shorts. Works regardless of account funding."""
        coin = _coin_of(instrument)
        meta, ctxs = await asyncio.to_thread(self._info.meta_and_asset_ctxs)
        for asset, ctx in zip(meta.get("universe", []), ctxs):
            if asset.get("name") == coin:
                return float(ctx.get("funding", 0.0) or 0.0)
        raise KeyError(f"no Hyperliquid perp for instrument={instrument!r} (coin={coin!r})")

    async def get_open_positions(self) -> list[HedgePosition]:
        """All open perp positions on the master account (empty if none)."""
        st = await self._user_state()
        out: list[HedgePosition] = []
        for ap in st.get("assetPositions", []):
            szi = float(ap.get("position", {}).get("szi", 0.0) or 0.0)
            if szi != 0.0:
                out.append(self._position_from_asset(ap))
        return out

    async def get_position(self, position_id: int) -> HedgePosition:
        """The open position for the coin behind `position_id`. Raises if the
        account holds no position there."""
        coin = self._coin_for(position_id)
        st = await self._user_state()
        for ap in st.get("assetPositions", []):
            if ap.get("position", {}).get("coin") == coin:
                if float(ap["position"].get("szi", 0.0) or 0.0) != 0.0:
                    return self._position_from_asset(ap)
        raise KeyError(f"no open Hyperliquid position for {coin} (position_id={position_id})")

    # ----- writes (gated on a funded master account) ----------------------

    async def _require_funded(self) -> float:
        """Refuse to trade unless the master account holds usable margin."""
        account_value = await self.get_account_value()
        if account_value < _MIN_ACCOUNT_VALUE_USDC:
            raise RuntimeError(
                f"Hyperliquid master account {self._master} is unfunded "
                f"(accountValue={account_value} USDC). Deposit USDC margin at "
                "app.hyperliquid-testnet.xyz (the HL bridge — NOT a CCTP "
                "contract) before opening a hedge. Reads (funding rate, "
                "positions, account value) work without funding."
            )
        return account_value

    @staticmethod
    def _check_filled(result: dict, action: str) -> tuple[float, float]:
        """Pull (filled_size, avg_price) out of an Exchange order result,
        raising with the venue's own error text if it didn't fill."""
        if result.get("status") != "ok":
            raise RuntimeError(f"Hyperliquid {action} rejected: {result}")
        statuses = result["response"]["data"]["statuses"]
        for s in statuses:
            if "error" in s:
                raise RuntimeError(f"Hyperliquid {action} error: {s['error']}")
        # A market order reports under "filled"; a resting limit under "resting".
        for s in statuses:
            if "filled" in s:
                f = s["filled"]
                return float(f["totalSz"]), float(f["avgPx"])
        return 0.0, 0.0

    async def open_position(
        self,
        instrument: str,
        side: str,
        size: float,
        margin_amount: float,
        leverage: float = 1.0,
        stop_loss: Optional[float] = None,
    ) -> HedgePosition:
        """Open a perp hedge leg. `side` is "long"/"short" (HedgeSide);
        long -> buy, short -> sell. Sets leverage first, then sends a market
        order via the API wallet on behalf of the master account.

        Gated: raises RuntimeError if the master account holds no margin."""
        await self._require_funded()

        coin = _coin_of(instrument)
        is_buy = side.lower() == "long"
        lev = max(1, int(round(leverage)))

        # Set leverage (cross) before opening. Best-effort: a no-op change can
        # return a benign error, so only raise on a hard failure.
        lev_res = await asyncio.to_thread(self._exchange.update_leverage, lev, coin, True)
        if isinstance(lev_res, dict) and lev_res.get("status") not in ("ok", None):
            raise RuntimeError(f"Hyperliquid set-leverage failed for {coin}: {lev_res}")

        result = await asyncio.to_thread(self._exchange.market_open, coin, is_buy, size)
        filled_sz, avg_px = self._check_filled(result, "open")

        if stop_loss is not None:
            # Reduce-only stop on the opposite side, triggered at stop_loss.
            await self._place_stop(coin, is_buy, filled_sz or size, stop_loss)

        # Re-read so margin_amount / entry reflect the venue's bookkeeping.
        try:
            return await self.get_position(self._id_for(coin))
        except KeyError:
            return HedgePosition(
                position_id=self._id_for(coin),
                venue=VENUE,
                instrument=f"{coin}-PERP",
                side=side.lower(),
                size=filled_sz or size,
                entry_price=avg_px,
                margin_asset="USDC",
                margin_amount=margin_amount,
                status="open",
            )

    async def _place_stop(self, coin: str, was_buy: bool, size: float, trigger_px: float) -> None:
        """Attach a reduce-only stop-market on the opposite side of the entry."""
        from hyperliquid.utils.signing import OrderType

        stop_type: OrderType = {
            "trigger": {"triggerPx": trigger_px, "isMarket": True, "tpsl": "sl"}
        }
        await asyncio.to_thread(
            self._exchange.order,
            coin,
            not was_buy,        # close direction
            size,
            trigger_px,
            stop_type,
            True,               # reduce_only
        )

    async def close_position(self, position_id: int) -> HedgePosition:
        """Market-close the position behind `position_id`. Returns a closed
        HedgePosition snapshot. Gated on a funded account (closing is itself a
        signed order)."""
        await self._require_funded()
        coin = self._coin_for(position_id)

        # Snapshot before closing so we can report side/size/entry/pnl.
        try:
            before = await self.get_position(position_id)
        except KeyError:
            before = HedgePosition(
                position_id=position_id, venue=VENUE, instrument=f"{coin}-PERP",
                side="", size=0.0, entry_price=0.0, margin_asset="USDC",
                margin_amount=0.0, status="closed",
            )

        result = await asyncio.to_thread(self._exchange.market_close, coin)
        # market_close returns None / a no-op-ish result if there was nothing to
        # close; only surface a true rejection.
        if isinstance(result, dict):
            self._check_filled(result, "close")

        return HedgePosition(
            position_id=position_id,
            venue=VENUE,
            instrument=before.instrument or f"{coin}-PERP",
            side=before.side,
            size=before.size,
            entry_price=before.entry_price,
            margin_asset="USDC",
            margin_amount=before.margin_amount,
            status="closed",
            pnl_usdc=before.pnl_usdc,
        )

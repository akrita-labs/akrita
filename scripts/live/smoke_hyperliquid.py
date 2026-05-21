"""
Hyperliquid hedge-adapter smoke test.

Proves the live HyperliquidReal surface end to end against HL testnet:

  READS (always run — no margin required):
    - master account value + withdrawable margin
    - current BTC / ETH funding rates
    - any open perp positions on the master account

  WRITE round-trip (only if the master account is FUNDED):
    - set leverage, open a minimal BTC short, read it back, then close it.
  If the account is unfunded (accountValue ~ 0) the write is SKIPPED with a
  clear message — we never fire an order that will obviously bounce.

  Force-skip the write even on a funded account with --read-only.

Usage:
    .venv/bin/python scripts/live/smoke_hyperliquid.py [--read-only]

Exit 0 if all reads succeed (write is best-effort / informational).
"""
from __future__ import annotations

import asyncio
import sys

from adapters.real.hyperliquid import HyperliquidReal, _MIN_ACCOUNT_VALUE_USDC
from shared.config import settings


# Deliberately tiny — only ever submitted on a funded account.
_SMOKE_COIN = "BTC-PERP"
_SMOKE_SIDE = "short"
_SMOKE_SIZE = 0.001
_SMOKE_MARGIN_USDC = 50.0
_SMOKE_LEVERAGE = 2.0


async def run(read_only: bool) -> int:
    hl = HyperliquidReal()
    print(f"HL testnet: {settings.hl_url}")
    print(f"  master account: {hl._master}")
    print(f"  API wallet (signer): {hl._signer.address}\n")

    # ----- reads -----------------------------------------------------------
    print("--- account state (reads) ---")
    account_value = await hl.get_account_value()
    withdrawable = await hl.get_withdrawable()
    print(f"  accountValue:  {account_value} USDC")
    print(f"  withdrawable:  {withdrawable} USDC")

    print("\n--- funding rates (reads) ---")
    btc_funding = await hl.get_funding_rate("BTC-PERP")
    eth_funding = await hl.get_funding_rate("ETH-PERP")
    print(f"  BTC-PERP hourly funding: {btc_funding}")
    print(f"  ETH-PERP hourly funding: {eth_funding}")

    print("\n--- open positions (reads) ---")
    positions = await hl.get_open_positions()
    if not positions:
        print("  (none)")
    for p in positions:
        print(
            f"  {p.instrument} {p.side} size={p.size} entry={p.entry_price} "
            f"margin={p.margin_amount} USDC pnl={p.pnl_usdc} USDC"
        )

    funded = account_value >= _MIN_ACCOUNT_VALUE_USDC

    # ----- write round-trip (only if funded) -------------------------------
    print("\n--- write path ---")
    if read_only:
        print("  --read-only set; skipping the open/close round-trip.")
        return 0
    if not funded:
        print(
            f"  account UNFUNDED (accountValue={account_value} USDC < "
            f"{_MIN_ACCOUNT_VALUE_USDC}). Skipping open/close.\n"
            "  Fund USDC margin at app.hyperliquid-testnet.xyz (the HL bridge,\n"
            "  NOT a CCTP contract) to exercise the write path."
        )
        # Show that the gate fires with a clear error, as the agent will see it.
        try:
            await hl.open_position(
                _SMOKE_COIN, _SMOKE_SIDE, _SMOKE_SIZE, _SMOKE_MARGIN_USDC,
                leverage=_SMOKE_LEVERAGE,
            )
        except RuntimeError as e:
            print(f"\n  open_position gate (expected): {e}")
        return 0

    print(
        f"  account FUNDED ({account_value} USDC). Opening minimal "
        f"{_SMOKE_SIDE} {_SMOKE_SIZE} {_SMOKE_COIN} @ {_SMOKE_LEVERAGE}x …"
    )
    opened = await hl.open_position(
        _SMOKE_COIN, _SMOKE_SIDE, _SMOKE_SIZE, _SMOKE_MARGIN_USDC,
        leverage=_SMOKE_LEVERAGE,
    )
    print(
        f"  opened: id={opened.position_id} {opened.instrument} {opened.side} "
        f"size={opened.size} entry={opened.entry_price} "
        f"margin={opened.margin_amount} USDC"
    )

    readback = await hl.get_position(opened.position_id)
    print(f"  read back: size={readback.size} pnl={readback.pnl_usdc} USDC")

    print("  closing …")
    closed = await hl.close_position(opened.position_id)
    print(f"  closed: id={closed.position_id} status={closed.status}")
    return 0


def main() -> int:
    read_only = "--read-only" in sys.argv
    return asyncio.run(run(read_only))


if __name__ == "__main__":
    sys.exit(main())

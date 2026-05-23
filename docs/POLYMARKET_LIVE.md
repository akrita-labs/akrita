# Polymarket V2 — going live (PR 3)

## Status

| Capability | State |
| --- | --- |
| Market reads (orderbook, question, recent fills) | ✅ live against `clob.polymarket.com` |
| Builder code in `.env` (`POLY_BUILDER_CODE`) | ✅ set, format-valid |
| V2 API creds (`POLY_API_KEY/SECRET/PASSPHRASE`) | ✅ set |
| Order signer EOA | ✅ provisioned (`secrets/polymarket_signer.json`) |
| **pUSD collateral on signer** | ❌ **blocks live order submission** |
| **CTF / exchange allowances** | ❌ **blocks live order submission** |

`PolymarketReal.submit_quote` / `cancel_order` are built and wire the V2
`BuilderConfig` (so fills attribute to our builder code), but they refuse to
run until the two ❌ items below are done.

## Why a separate signer EOA

Polymarket V2 signs orders with a local EOA key (`signature_type=0`). Our
keeper wallets are Circle Developer-Controlled (MPC) — no extractable key —
so a dedicated EOA holds collateral and signs orders. **Builder attribution
is independent of the signing wallet**: fees accrue to `POLY_BUILDER_CODE`
regardless of which EOA signs, so the thesis (attributed volume) is unaffected.

Signer address (fund this): see `secrets/polymarket_signer.json` →
`0xBE5573E209D379D01bB0c8a57c3b3C584F76E92D`.

## Unblock steps

1. **Fund the signer with MATIC (Amoy) or POL** for gas — small drip from a
   faucet to `0xBE55…E92D`.
2. **Get pUSD collateral.** V2 collateral is pUSD, not USDC.e. Wrap USDC at
   the V2 Collateral Onramp into the signer EOA. (Testnet: confirm the Amoy
   onramp address in the V2 docs.)
3. **Approve allowances** so the CTF Exchange can move the signer's pUSD +
   conditional tokens. `py-clob-client` exposes the allowance helpers; the
   first `submit_quote` will need these set once.

Once funded + approved, `PolymarketReal.submit_quote` submits attributed
bid/ask orders and the PR 3 exit gate (an `OrderFilled` carrying our builder
code, linked back to a pricing-decision trace) becomes reachable.

## Deferred to follow-ups (not blocking the read path)

- **WebSocket ingestion** — market channel (orderbook/trade) + authenticated
  user channel (order status/fills). NOMOS currently polls `/book`, which
  works; WS reduces latency and is required for the fill-reconciliation loop.
- **Order/fill persistence** — `OrderRepo` / `FillRepo` exist (PR 1); wiring
  `submit_quote` results + `OrderFilled` events into them is moot until orders
  actually submit.
- **Quote pause/backoff controls** — stale-heartbeat / spread-floor /
  builder-code-absent pauses live in the NOMOS quoting loop (PR 4–5 window).

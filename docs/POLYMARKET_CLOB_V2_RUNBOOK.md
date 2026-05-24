# Polymarket CLOB V2 migration — runbook (Amoy testnet)

> Status: code migration **written, not runtime-verified** (staged via "I write it, you run it").
> Polymarket replaced its stack on **2026-04-28** (CLOB V2 + pUSD). The legacy
> `py-clob-client` no longer works against production; this migrates AKRITA's
> Polymarket write path to the official **`py-clob-client-v2`** SDK.

## What changed in code

- **`adapters/real/polymarket.py`** — write path (`_get_client` / `submit_quote` /
  `cancel_order`) now uses `py_clob_client_v2`:
  - `ClobClient(host, chain_id=settings.poly_chain_id, key=<signer>, signature_type=EOA(0), funder=<signer addr>, builder_config=BuilderConfig(builder_address, builder_code))`.
  - Orders are `OrderArgsV2(..., builder_code=<bytes32>)` → `create_order` → `post_order(GTC)`.
  - L2 API creds: taken from `.env` if all three are set, else **derived from the signer key** (`create_or_derive_api_key`).
  - The readiness gate (`_require_writes_ready`) still raises **before** the SDK is imported, so the GATED path needs neither the package nor network. Reads are unchanged.
- **`shared/config.py`** — new `poly_chain_id: int = 137` (set `80002` for Amoy).
- **`scripts/bootstrap/poly_collateral_onramp.py`** — `--check` / `--approve` helper that reports the signer's pUSD balance and sets CTF/exchange allowances via the CLOB V2 API.
- **SDK** — `py-clob-client-v2==1.0.1` installed into `.venv` (official Polymarket Engineering package).

## Prerequisites you must confirm (not in the repo)

| Item | Where to get it |
|---|---|
| **Amoy CLOB host** (`POLY_RELAYER_URL`) | Polymarket V2 docs — the testnet CLOB endpoint. The SDK does **not** bake it in. |
| **pUSD token + Collateral Onramp (Amoy)** | Polymarket pUSD / contracts docs. Needed to wrap USDC→pUSD. |
| **Amoy RPC** (`POLYGON_RPC_URL`) | e.g. `https://rpc-amoy.polygon.technology` |
| **Test POL + USDC** | Polygon Amoy faucets, sent to the signer `0xBE55…E92D`. |

The V2 contract config for Amoy (80002) ships **inside the SDK**
(`py_clob_client_v2/config.py`): `exchange_v2`, `neg_risk_exchange_v2`,
`conditional_tokens`. You generally don't need to pass these yourself.

## Steps (run these yourself)

1. **Point config at Amoy** — in `.env`:
   ```
   POLY_CHAIN_ID=80002
   POLY_RELAYER_URL=<Amoy CLOB host — confirm from V2 docs>
   POLYGON_RPC_URL=https://rpc-amoy.polygon.technology
   ```
   (Leave `POLY_API_KEY/SECRET/PASSPHRASE` blank to derive fresh V2 creds from the signer, or set valid V2 creds.)

2. **Fund the signer** `0xBE5573E209D379D01bB0c8a57c3b3C584F76E92D`:
   - POL (gas) + USDC on Amoy, via faucets.

3. **Wrap USDC → pUSD** at the V2 Collateral Onramp (address from Polymarket pUSD docs). This is the one step neither the SDK nor this repo automates.

4. **Set allowances**:
   ```
   .venv/bin/python scripts/bootstrap/poly_collateral_onramp.py --check
   .venv/bin/python scripts/bootstrap/poly_collateral_onramp.py --approve
   ```

5. **Flip the flag + restart**:
   - `POLY_COLLATERAL_READY=1` in `.env`
   - `sudo systemctl restart akrita-orchestrator` (gated: `RESTART-CONFIRMED`).

6. **Verify**: post a NOMOS pricing decision (or watch the dashboard) — the
   `LEVERAGE LIMIT / collateral not ready` gate should clear and orders should
   submit attributed to the builder code.

## Validate before going live

```
.venv/bin/python -m pytest -q orchestrator/tests/test_real_adapters.py
```
The gated-write test asserts `submit_quote` raises until `POLY_COLLATERAL_READY=1`.

## Rollback

The change is additive: revert `adapters/real/polymarket.py` + `shared/config.py`
(the old `py-clob-client` is still installed) and restart. `py-clob-client-v2`
can be removed with `pip uninstall py-clob-client-v2` if desired.

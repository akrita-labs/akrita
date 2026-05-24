#!/usr/bin/env python
"""
Polymarket CLOB V2 — collateral onramp + exchange allowances for the signer EOA.

The Polymarket V2 trading EOA (secrets/polymarket_signer.json) must hold **pUSD**
collateral and have its CTF / exchange allowances set before NOMOS order
submission can leave the GATED state. This helper drives the parts the CLOB V2
SDK can automate:

  --check    (default) report the signer address, the configured host/chain, and
             the on-chain COLLATERAL (pUSD) balance + allowance the CLOB sees.
  --approve  call update_balance_allowance for COLLATERAL and CONDITIONAL so the
             CTF V2 / Neg-Risk V2 exchanges can move the signer's pUSD + tokens.

NOT automated here (do this first, see the RUNBOOK):
  * Fund the signer with gas (POL on Amoy/Polygon) and USDC.
  * Wrap USDC -> pUSD at the Polymarket V2 Collateral Onramp. pUSD is the V2
    collateral token; the onramp contract address is published on Polymarket's
    pUSD / contracts docs and is NOT shipped in this repo. Confirm it there.

After pUSD is in the signer and allowances are approved, set
POLY_COLLATERAL_READY=1 in .env and restart the orchestrator.

Run:  .venv/bin/python scripts/bootstrap/poly_collateral_onramp.py --check
      .venv/bin/python scripts/bootstrap/poly_collateral_onramp.py --approve
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.config import settings  # noqa: E402


def _load_signer() -> dict:
    path = REPO_ROOT / "secrets" / "polymarket_signer.json"
    if not path.exists():
        raise SystemExit(
            "secrets/polymarket_signer.json not found — provision the signer EOA first "
            "(see docs/POLYMARKET_LIVE.md)."
        )
    return json.loads(path.read_text())


def _build_client():
    """CLOB V2 client signed by the local EOA, with builder code + derived L2 creds."""
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import ApiCreds, BuilderConfig
    from py_clob_client_v2.order_utils.model.signature_type_v2 import SignatureTypeV2

    signer = _load_signer()
    addr = signer["address"]
    creds = None
    if settings.poly_api_key and settings.poly_api_secret and settings.poly_api_passphrase:
        creds = ApiCreds(
            api_key=settings.poly_api_key,
            api_secret=settings.poly_api_secret,
            api_passphrase=settings.poly_api_passphrase,
        )
    client = ClobClient(
        host=settings.poly_relayer_url or "https://clob.polymarket.com",
        chain_id=settings.poly_chain_id,
        key=signer["privateKey"],
        creds=creds,
        signature_type=SignatureTypeV2.EOA,
        funder=addr,
        builder_config=BuilderConfig(builder_address=addr, builder_code=settings.poly_builder_code),
    )
    if creds is None:
        client.set_api_creds(client.create_or_derive_api_key())
    return client, addr


def cmd_check() -> None:
    from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams

    client, addr = _build_client()
    print(f"signer EOA   : {addr}")
    print(f"CLOB host    : {settings.poly_relayer_url}")
    print(f"chain_id     : {settings.poly_chain_id}  ({'Amoy testnet' if settings.poly_chain_id == 80002 else 'Polygon mainnet' if settings.poly_chain_id == 137 else 'unknown'})")
    print(f"builder code : {settings.poly_builder_code[:10]}…")
    ba = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
    print(f"pUSD balance/allowance (COLLATERAL): {ba}")


def cmd_approve() -> None:
    from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams

    client, addr = _build_client()
    print(f"approving exchange allowances for {addr} on chain {settings.poly_chain_id}…")
    res_c = client.update_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
    print(f"  COLLATERAL (pUSD): {res_c}")
    res_t = client.update_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL))
    print(f"  CONDITIONAL      : {res_t}")
    print("done. If the signer holds pUSD, set POLY_COLLATERAL_READY=1 and restart.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Polymarket CLOB V2 collateral onramp / allowances")
    ap.add_argument("--approve", action="store_true", help="set CTF/exchange allowances (COLLATERAL + CONDITIONAL)")
    args = ap.parse_args()
    if args.approve:
        cmd_approve()
    else:
        cmd_check()


if __name__ == "__main__":
    main()

"""
Bootstrap: subscribe Arc testnet USDC into testnet USYC, signed by the
treasury-keeper Circle MPC wallet.

Why this script:
  - The treasury wallet is a Circle Developer-Controlled Wallet (MPC). It
    has no extractable private key, so it cannot connect to the
    `usyc.dev.hashnote.com` dApp the way a MetaMask wallet does.
  - Instead we drive the Teller contract directly via Circle's
    `contract execution transaction` API, signed server-side by Circle.

What it does:
  1. USDC.approve(USYC_TELLER, amount)
  2. USYC_TELLER.deposit(amount, treasury_addr)
       — ERC-4626 vault: USDC in, USYC shares out
  3. Read both balances on-chain before and after, print the delta.

Usage:
  .venv/bin/python scripts/bootstrap/usyc_subscribe.py [usdc_amount]

  usdc_amount defaults to 5 USDC. Pass a different number to subscribe more,
  e.g. `... usyc_subscribe.py 10` for 10 USDC.

  Symmetric redeem flow is `usyc_redeem.py`; not in this script.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from circle.web3 import developer_controlled_wallets as dcw
from circle.web3 import utils


# ---------------------------------------------------------------------------
# Arc testnet constants — verified against docs.arc.io/arc/references/contract-addresses
# ---------------------------------------------------------------------------

ARC_RPC = "https://rpc.testnet.arc.network"
USDC_ADDR = "0x3600000000000000000000000000000000000000"
USYC_ADDR = "0xe9185F0c5F296Ed1797AaE4238D26CCaBEadb86C"
USYC_TELLER_ADDR = "0x9fdF14c5B14173D74C08Af27AebFf39240dC105A"
USDC_DECIMALS = 6
USYC_DECIMALS = 6

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
SECRET_FILE = REPO_ROOT / "secrets" / "circle_entity_secret.txt"

POLL_INTERVAL_SEC = 3
POLL_TIMEOUT_SEC = 180


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def rpc(method: str, params: list) -> dict:
    req = urllib.request.Request(
        ARC_RPC,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "akrita-bootstrap"},
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def erc20_balance_of(token: str, holder: str) -> int:
    data = "0x70a08231" + "0" * 24 + holder.lower().removeprefix("0x")
    r = rpc("eth_call", [{"to": token, "data": data}, "latest"])
    return int(r["result"], 16) if r.get("result") and r["result"] != "0x" else 0


def submit_contract_call(
    api: dcw.TransactionsApi,
    wallet_id: str,
    contract_address: str,
    abi_signature: str,
    abi_parameters: list,
    description: str,
) -> str:
    """Submit a contract execution via Circle. Returns the Circle tx ID."""
    wrapped_params = [dcw.AbiParametersInner(p) for p in abi_parameters]
    req = dcw.CreateContractExecutionTransactionForDeveloperRequest(
        idempotencyKey=str(uuid.uuid4()),
        entitySecretCiphertext="",          # auto-filled by SDK wrapper
        walletId=wallet_id,
        contractAddress=contract_address,
        abiFunctionSignature=abi_signature,
        abiParameters=wrapped_params,
        feeLevel=dcw.FeeLevel.MEDIUM,
    )
    print(f"[submit] {description}: {abi_signature}({abi_parameters})")
    resp = api.create_developer_transaction_contract_execution(req)
    tx_id = resp.data.id
    print(f"[submit] queued circle_tx_id={tx_id}")
    return tx_id


def wait_for_confirmation(api: dcw.TransactionsApi, tx_id: str) -> dict:
    """Poll Circle until the transaction is CONFIRMED, COMPLETE, or FAILED."""
    started = time.time()
    last_state = None
    while time.time() - started < POLL_TIMEOUT_SEC:
        resp = api.get_transaction(id=tx_id)
        tx = resp.data.transaction
        state = getattr(tx.state, "value", str(tx.state))
        if state != last_state:
            print(f"[poll]   {tx_id[:13]}…  state={state}  tx_hash={getattr(tx, 'tx_hash', None) or '<pending>'}")
            last_state = state
        if state in ("CONFIRMED", "COMPLETE"):
            return tx.model_dump()
        if state in ("FAILED", "CANCELLED", "DENIED"):
            raise SystemExit(f"Circle tx {tx_id} ended in state={state}: {tx.model_dump()}")
        time.sleep(POLL_INTERVAL_SEC)
    raise SystemExit(f"Circle tx {tx_id} did not confirm within {POLL_TIMEOUT_SEC}s")


def main() -> int:
    if not ENV_FILE.exists():
        raise SystemExit(f".env not found at {ENV_FILE}")
    env = read_env(ENV_FILE)

    if env.get("USYC_WALLET_ALLOWLISTED", "false").lower() != "true":
        raise SystemExit(
            "USYC_WALLET_ALLOWLISTED is not true in .env. The treasury wallet "
            "must be allowlisted by Circle before subscribe will succeed."
        )

    treasury_wallet_id = env.get("TREASURY_WALLET_ID_ARC", "").strip()
    treasury_addr = env.get("TREASURY_WALLET_ADDR", "").strip()
    if not treasury_wallet_id or not treasury_addr:
        raise SystemExit("TREASURY_WALLET_ID_ARC + TREASURY_WALLET_ADDR must be set in .env")

    api_key = env.get("CIRCLE_API_KEY", "").strip()
    if not api_key or api_key.count(":") != 2:
        raise SystemExit("CIRCLE_API_KEY missing or malformed")
    if not SECRET_FILE.exists():
        raise SystemExit(f"Entity secret missing at {SECRET_FILE}")
    entity_secret = SECRET_FILE.read_text().strip()

    # Amount in USDC (default 5).
    usdc_human = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    amount_wei = int(round(usdc_human * 10**USDC_DECIMALS))

    print("=" * 70)
    print(f"USYC subscribe — treasury wallet {treasury_addr}")
    print(f"  Amount: {usdc_human} USDC ({amount_wei} base units)")
    print(f"  Teller: {USYC_TELLER_ADDR}")
    print("=" * 70)

    # ----- Pre-state ----------------------------------------------------------
    usdc_before = erc20_balance_of(USDC_ADDR, treasury_addr)
    usyc_before = erc20_balance_of(USYC_ADDR, treasury_addr)
    print(f"\n[pre]  USDC balance: {usdc_before / 10**USDC_DECIMALS:.6f}")
    print(f"[pre]  USYC balance: {usyc_before / 10**USYC_DECIMALS:.6f}")
    if usdc_before < amount_wei:
        raise SystemExit(
            f"insufficient USDC: have {usdc_before / 10**USDC_DECIMALS:.6f}, "
            f"need {usdc_human}"
        )

    # ----- Build client + APIs -----------------------------------------------
    client = utils.init_developer_controlled_wallets_client(
        api_key=api_key, entity_secret=entity_secret
    )
    tx_api = dcw.TransactionsApi(client)

    # ----- Step 1: USDC.approve(USYC_TELLER, amount) -------------------------
    approve_tx_id = submit_contract_call(
        tx_api,
        treasury_wallet_id,
        USDC_ADDR,
        "approve(address,uint256)",
        [USYC_TELLER_ADDR, str(amount_wei)],
        description="USDC.approve",
    )
    approve_tx = wait_for_confirmation(tx_api, approve_tx_id)
    print(f"[done] approve on-chain tx: {approve_tx.get('tx_hash')}")

    # ----- Step 2: Teller.deposit(amount, treasury_addr) ---------------------
    # ERC-4626: deposit(uint256 assets, address receiver) -> uint256 shares
    deposit_tx_id = submit_contract_call(
        tx_api,
        treasury_wallet_id,
        USYC_TELLER_ADDR,
        "deposit(uint256,address)",
        [str(amount_wei), treasury_addr],
        description="USYC.deposit",
    )
    deposit_tx = wait_for_confirmation(tx_api, deposit_tx_id)
    print(f"[done] deposit on-chain tx: {deposit_tx.get('tx_hash')}")

    # ----- Post-state --------------------------------------------------------
    usdc_after = erc20_balance_of(USDC_ADDR, treasury_addr)
    usyc_after = erc20_balance_of(USYC_ADDR, treasury_addr)
    print(f"\n[post] USDC balance: {usdc_after / 10**USDC_DECIMALS:.6f}  "
          f"(Δ {(usdc_after - usdc_before) / 10**USDC_DECIMALS:+.6f})")
    print(f"[post] USYC balance: {usyc_after / 10**USYC_DECIMALS:.6f}  "
          f"(Δ {(usyc_after - usyc_before) / 10**USYC_DECIMALS:+.6f})")
    print("\n✓ subscribe complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())

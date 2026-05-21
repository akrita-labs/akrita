"""
USYC Teller permission verifier.

Run after Circle confirms they granted ROLE_INVESTOR on the Teller's
RolesAuthority. Returns 0 if all gates pass (deposit is unblocked),
non-zero otherwise.

  .venv/bin/python scripts/bootstrap/usyc_check_permission.py
"""
from __future__ import annotations

import json
import sys
import urllib.request

from eth_utils import keccak

ARC_RPC = "https://rpc.testnet.arc.network"
USDC = "0x3600000000000000000000000000000000000000"
USYC = "0xe9185F0c5F296Ed1797AaE4238D26CCaBEadb86C"
TELLER = "0x9fdF14c5B14173D74C08Af27AebFf39240dC105A"
AUTHORITY = "0xcc205224862c7641930c87679e98999d23c26113"
TREASURY = "0x94a13d1b20f0100e62f1361563a36966cc90e269"


def rpc(method: str, params: list) -> dict:
    req = urllib.request.Request(
        ARC_RPC,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "akrita-check"},
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def sel(sig: str) -> str:
    return keccak(text=sig).hex()[:8]


def pad_addr(a: str) -> str:
    return "0" * 24 + a.lower().removeprefix("0x")


def call(to: str, data: str) -> str:
    r = rpc("eth_call", [{"to": to, "data": "0x" + data}, "latest"])
    return r.get("result") or "0x"


def is_true(hexword: str) -> bool:
    return hexword and int(hexword, 16) == 1


def main() -> int:
    deposit_sel = sel("deposit(uint256,address)")
    transfer_sel = sel("transfer(address,uint256)")
    can_call_sel = sel("canCall(address,address,bytes4)")
    get_roles_sel = sel("getUserRoles(address)")

    deposit_can = call(
        AUTHORITY,
        can_call_sel + pad_addr(TREASURY) + pad_addr(TELLER) + deposit_sel.ljust(64, "0"),
    )
    transfer_can = call(
        AUTHORITY,
        can_call_sel + pad_addr(TREASURY) + pad_addr(USYC) + transfer_sel.ljust(64, "0"),
    )
    roles = call(AUTHORITY, get_roles_sel + pad_addr(TREASURY))
    roles_int = int(roles, 16) if roles and roles != "0x" else 0
    role_bits = [i for i in range(256) if roles_int & (1 << i)]

    print(f"treasury wallet:              {TREASURY}")
    print(f"RolesAuthority.getUserRoles:  {roles}")
    print(f"  → role bits set:             {role_bits or '<none>'}")
    print()
    print(f"canCall(treasury, teller, deposit):        "
          f"{'✓ true' if is_true(deposit_can) else '✗ false'}")
    print(f"canCall(treasury, USYC,   transfer):       "
          f"{'✓ true' if is_true(transfer_can) else '✗ false'}")

    if is_true(deposit_can) and is_true(transfer_can):
        print("\n✓ All gates pass. Safe to retry usyc_subscribe.py.")
        return 0
    print("\n✗ Still blocked. Wait for Circle Support to complete the role grant.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

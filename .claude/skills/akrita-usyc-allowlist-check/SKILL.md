---
name: akrita-usyc-allowlist-check
description: >
  Check whether the AKRITA AGROS treasury wallet holds the USYC RolesAuthority grant
  on Arc. Use when the user says "check USYC allowlist", "is AGROS allowlisted", "can
  we subscribe to USYC yet", or before any AGROS USYC subscribe/redeem. Read-only:
  runs scripts/bootstrap/usyc_check_permission.py (eth_call only, no signing).
allowed-tools: Bash(.venv/bin/python:*), Read
---

# USYC allowlist check

USYC writes (`deposit`/`redeem`) revert with `NotPermissioned()` until Circle Support
grants the treasury keeper the investor role on the Teller's `RolesAuthority`. This
skill verifies that grant. It is the external dependency that gates AGROS Tier A live
writes (`USYC_WALLET_ALLOWLISTED`).

## Run
```bash
cd /home/ubuntu/akrita && .venv/bin/python scripts/bootstrap/usyc_check_permission.py
```
It prints the treasury wallet, its `RolesAuthority` role bits, and:
```
canCall(treasury, teller, deposit):  true|false
canCall(treasury, USYC,   transfer): true|false
```
Exit code **0** = all gates pass; **non-zero** = still blocked.

## Interpret
- Exit 0 / "✓ All gates pass" → the grant is live. Tell the operator they may set
  `USYC_WALLET_ALLOWLISTED=true` in `.env` and restart the orchestrator
  (see `/akrita-stack`). USYC subscribe/redeem will then execute.
- Exit non-zero / "✗ Still blocked" → this is an **external Circle Support
  dependency** with an unbounded lead time. The role grant must be completed on the
  Teller's `RolesAuthority` before retrying. Do not flip `USYC_WALLET_ALLOWLISTED`.

## Notes
- Read-only; safe to run anytime. Uses raw Arc JSON-RPC (`eth_call`), not the Circle SDK.
- Underlying adapter context: `adapters/real/usyc.py` (Teller ERC-4626 deposit/redeem).

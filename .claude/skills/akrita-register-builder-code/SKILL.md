---
name: akrita-register-builder-code
description: >
  Register a Polymarket builder code for an AKRITA operator and record it on the Arc
  BuilderRegistry. Use for "register a builder code", "onboard an operator", "seed the
  operators", "register agent on BuilderRegistry". Spends Arc gas (owner-signed
  registerAgent) and writes tenant state. Requires the token REGISTER-CONFIRMED.
  Never auto-run.
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash(.venv/bin/python:*), Bash(curl:*), Read
---

# AKRITA register builder code

> **Confirmation gate.** Do NOT run any registration command until the user's message
> contains the literal token `REGISTER-CONFIRMED`. If absent, stop and ask. The
> on-chain leg spends gas and is signed with the Arc owner key.

The on-chain method is **`registerAgent(uint256 agentId, bytes32 builderCode,
address controllerWallet)`** in `contracts/src/BuilderRegistry.sol` (there is no
`setBuilderCode`/`registerBuilder`). System agents are ids 1/2/3; user operators
start at agentId 100. Registration is owner-only ([[builder-registry-signing]]:
signed with the raw deployer key, not Circle MPC).

## Bulk seed (the 12 curated operators)
```bash
cd /home/ubuntu/akrita
.venv/bin/python scripts/bootstrap/seed_operators.py            # creates users + registers on-chain
# flags: --count N | --base-url http://localhost:8000 | --no-register (store codes, skip on-chain)
```
Idempotent: existing handles are skipped; codes already on-chain adopt their existing agentId.

## Single operator (manual)
1. Create the user: `curl -sS -X POST http://127.0.0.1:8000/api/users -H 'Content-Type: application/json' -d '{"handle":"<handle>","display_name":"<name>"}'`
2. Register + go on-chain:
```bash
curl -sS -X POST http://127.0.0.1:8000/api/builder -H 'Content-Type: application/json' \
  -d '{"user_id":"<uuid>","builder_code":"0x<64hex>","auto_register":true}'
```
`POST /api/builder` encrypts any provided Polymarket creds (Fernet), allocates a free
agentId, and signs `registerAgent` on Arc. Re-running with the same code is idempotent.

## Verify
```bash
curl -sS http://127.0.0.1:8000/api/builder/<uuid> | python3 -m json.tool   # registration_status, onchain_agent_id, registration_tx
```
Check `registration_status: registered` and the `registration_tx` resolves on Arcscan.

## Notes
- Builder code must be a 0x-prefixed bytes32 (64 hex). Never paste real Polymarket API
  secrets into chat — pass them in the request body the operator controls, or omit.
- Dry run first with `--no-register` to provision codes without spending gas.

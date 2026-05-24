---
name: akrita-deploy-arc-contracts
description: >
  Deploy and verify AKRITA Foundry contracts (TraceRegistry, BuilderRegistry,
  SusdeAcceptance) to Arc. Use ONLY on explicit requests like "deploy contracts to
  Arc", "redeploy TraceRegistry", "ship SusdeAcceptance", "broadcast the deploy".
  Spends gas with the deployer key and mutates on-chain state. Requires the token
  DEPLOY-CONFIRMED-<network> (e.g. DEPLOY-CONFIRMED-testnet). Never auto-run.
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash(forge:*), Bash(cast:*), Bash(jq:*), Read
---

# AKRITA deploy Arc contracts

> **Confirmation gate.** Do NOT run `forge script … --broadcast` until the user's
> message contains the literal token `DEPLOY-CONFIRMED-<network>` matching the target
> (`DEPLOY-CONFIRMED-testnet` or `DEPLOY-CONFIRMED-mainnet`). If absent or mismatched,
> stop and ask. `forge build`/`forge test` (no broadcast) may run freely as pre-checks.

Scripts live in `contracts/script/`: `Deploy.s.sol` (TraceRegistry + BuilderRegistry,
pre-registers agents 1/2/3 + authorizes the trace keeper) and `DeploySusde.s.sol`
(SusdeAcceptance, EIP-712). Arc testnet chainId is **5042002**. Already-deployed:
`TRACE_REGISTRY_ADDR=0xd96C…9Ea4`, `BUILDER_REGISTRY_ADDR=0x060C…c223` — only redeploy
if explicitly asked (it strands the old address + requires re-wiring config).

## 1. Pre-checks (safe)
```bash
cd /home/ubuntu/akrita/contracts
forge build
forge test
```
Both must pass before any broadcast.

## 2. Deploy (GATED — needs DEPLOY-CONFIRMED-<network>)
The deployer key comes from the operator's environment (`PRIVATE_KEY`), never from
this skill. `$ARC_RPC_URL` is in `.env` (testnet: `https://rpc.testnet.arc.network`).
```bash
cd /home/ubuntu/akrita/contracts
PRIVATE_KEY=0x<deployer> forge script script/Deploy.s.sol --rpc-url "$ARC_RPC_URL" --broadcast
# or just the consent contract:
PRIVATE_KEY=0x<deployer> forge script script/DeploySusde.s.sol --rpc-url "$ARC_RPC_URL" --broadcast
```

## 3. Record the address (operator pastes — never auto-edit .env)
The deployed address is logged by the script and written to the broadcast artifact:
```bash
jq -r '.transactions[] | select(.contractName!=null) | "\(.contractName) \(.contractAddress)"' \
  contracts/broadcast/Deploy.s.sol/5042002/run-latest.json
# SusdeAcceptance:
jq -r '.transactions[]|select(.contractName=="SusdeAcceptance")|.contractAddress' \
  contracts/broadcast/DeploySusde.s.sol/5042002/run-latest.json
```
Print the exact `.env` line(s) for the operator to paste themselves, e.g.
`SUSDE_ACCEPTANCE_ADDR=0x…` (and `TRACE_REGISTRY_ADDR` / `BUILDER_REGISTRY_ADDR` if
those were redeployed). **Do not modify `.env` automatically.**

## 4. Re-wire + restart
After the operator updates `.env`, the orchestrator must reload config:
`/akrita-stack` → restart (the orchestrator logs the addresses at startup). If
TraceRegistry/BuilderRegistry changed, the frontend Arcscan links and any pinned
config also need updating — flag this.

## Notes
- `allowed-tools` does not enforce; the real gates are the permission prompt on
  `forge … --broadcast` (not allow-listed) + the DEPLOY-CONFIRMED token.
- Never echo or store `PRIVATE_KEY`. Confirm the target network in the broadcast
  output (`Chain 5042002`) before recording addresses.

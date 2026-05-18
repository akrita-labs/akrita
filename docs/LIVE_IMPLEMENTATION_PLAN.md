# AKRITA live implementation plan

This plan turns the current AKRITA prototype into the live Hephaestus-Prime system described in `hephaestus-prime-spec.pdf`: no mock trading path, no in-memory state as source of truth, and every consequential action backed by a verifiable external artifact.

## Definition of "alive"

The system is alive when `MOCK_MODE=0` can run continuously with:

- Real Circle-controlled wallets or explicitly approved signing wallets for pricing, hedge, treasury, and trace operations.
- Real Arc testnet deployments of `BuilderRegistry` and `TraceRegistry`.
- Real Polymarket V2 order submission with the registered `bytes32` builder code attached.
- Real Polymarket market data, private order stream, and `OrderFilled` event ingestion.
- Real USYC subscribe/redeem path where eligibility allows it, otherwise Arc testnet USYC with the limitation called out in the submission.
- Real Gateway transfers or CCTP fallback for cross-chain USDC movement.
- Real Hyperliquid or Arc-native perp hedge execution.
- Real IPFS pinning paid through x402/Gateway nanopayments, plus optional 0G redundancy.
- Postgres and Redis as the source of truth for decisions, nonces, fills, traces, balances, hedges, and treasury actions.
- A public dashboard and trace viewer that render live state and link to Arc, Polygon, IPFS, and Polymarket artifacts.

Demo replay can exist, but it must replay captured real testnet/mainnet artifacts. It must not be a substitute for the live path.

## Spec verification notes

The PDF is implementation-ready, but it explicitly says to verify external API surfaces before coding. As of May 18, 2026:

- Arc docs list Arc Testnet RPC as `https://rpc.testnet.arc.network`, chain ID `5042002`, symbol `USDC`, and explorer `https://testnet.arcscan.app`.
- Circle Paymaster docs list ERC-4337 support on Arbitrum, Avalanche, Base, Ethereum, Optimism, Polygon, and Unichain, but not Arc. Treat Arc Paymaster as conditional until confirmed; Arc already uses USDC as native gas, so live Arc transactions can proceed with funded USDC gas balances.
- Circle Gateway requires deposit through Gateway wallet contract methods, not raw ERC-20 transfers. Burn intents require EOA signatures, or an SCA must add an EOA delegate.
- Polymarket V2 builder attribution is part of the signed order struct. The `builder` field appears in `OrderFilled` events and must match the registered builder code.
- Polymarket WebSocket channels cover market orderbook/trade updates and authenticated user order updates. Use both; do not poll as the primary path.
- Circle USYC is only available to eligible non-US persons. If production eligibility is blocked, use testnet USYC and document the compliance constraint.
- Circle nanopayments use Gateway batched settlement and x402 payment flows. The current public SDK surface is TypeScript-first, so the cleanest implementation is a small TypeScript sidecar behind the Python trace pipeline.
- Hyperliquid official docs point to its Python SDK and support mainnet/testnet URLs. Testnet URL remains `https://api.hyperliquid-testnet.xyz`.

## Critical path

The highest-risk dependency is Polymarket builder-code admission. Apply and configure the builder profile before deeper implementation work. If admission is delayed, continue with testnet order attribution and captured testnet artifacts, but do not spend time polishing surfaces that do not prove attributed volume.

Second critical path is signing architecture. Gateway burn intents may require EOA signatures while Circle dev-controlled wallets may be EOAs or SCAs. Decide wallet account type early:

- Use EOAs for Gateway-heavy wallets when possible.
- If using SCAs, configure Gateway delegates and test transfer signing before writing treasury logic.
- Keep the trace wallet isolated and low-limit regardless of account type.

## Phase 0 - access, keys, and deployment skeleton

Target: all external accounts exist, no production code blocked on missing credentials.

Tasks:

- Apply for Polymarket V2 builder profile and record `POLY_BUILDER_CODE`.
- Create Polymarket API credentials for market data, user stream, and order submission.
- Create or authorize four wallets: `pricing-keeper`, `hedge-keeper`, `treasury-keeper`, `trace-keeper`.
- Decide EOA vs SCA per wallet, with explicit Gateway delegate strategy.
- Fund Arc testnet wallets with USDC gas from Circle faucet.
- File USYC testnet allowlist request for the treasury wallet.
- Create Pinata/web3.storage account or choose an x402-compatible pin provider.
- Create Hyperliquid testnet account, deposit minimal USDC, and generate API wallet if used.
- Add secret files under `secrets/` and keep `.env.example` aligned with every required variable.
- Update stale config defaults, especially `ARC_RPC_URL=https://rpc.testnet.arc.network`.

Exit gate:

- Four wallet addresses are known.
- Builder code request is submitted or approved.
- Arc testnet deployer can submit a transaction.
- Hyperliquid testnet account can query account state.
- Gateway signing path is decided and documented.

## Phase 1 - real adapter layer

Target: `MOCK_MODE=0` constructs a complete adapter container without raising `NotImplementedError`.

Repo changes:

- Add `adapters/real/` with concrete implementations behind the existing protocols.
- Split configuration into typed settings for all external clients.
- Add adapter-level smoke scripts under `scripts/live/`.
- Keep mocks available only for tests and demo replay.

Real adapters:

- `ArcReal`: `web3.py` or `eth_account` based calls, block reads, contract calls, transaction submission, receipt waiting, chain ID validation.
- `CircleWalletsReal`: wallet lookup, typed-data signing, transaction signing/broadcast where supported, balance reads.
- `GatewayReal`: Gateway balance reads, deposit status, burn intent construction, EOA/delegate signature, transfer attestation retrieval, destination mint call, CCTP fallback.
- `USYCReal`: subscribe, redeem, NAV read, APY read, settlement polling, idempotency keys, compliance/testnet mode flag.
- `NanopaymentReal`: Python facade that calls a TypeScript x402/Gateway sidecar for paid IPFS pinning.
- `PolymarketReal`: CLOB V2 SDK wrapper for orderbook, market metadata, order creation, builder-code attachment, cancel, private user stream, public market stream.
- `HyperliquidReal`: official Python SDK wrapper for open, close, position read, funding read, and stop-loss management.

Exit gate:

- `python scripts/live/smoke_arc.py` deploys or calls a known contract.
- `python scripts/live/smoke_wallets.py` signs typed data with each wallet.
- `python scripts/live/smoke_polymarket.py` builds a signed order with builder code in dry-run/testnet mode.
- `python scripts/live/smoke_gateway.py` reads unified balance and can execute a tiny test transfer where supported.
- `python scripts/live/smoke_hyperliquid.py` opens and closes a minimal testnet position.
- `python scripts/live/smoke_pin.py` pins bytes and verifies the returned CID.

## Phase 2 - persistence and replay safety

Target: restart-safe operation with traceable state and replay protection.

Repo changes:

- Add Postgres and Redis services to `docker-compose.yml`.
- Add migrations for `decisions`, `traces`, `fills`, `inventory_snapshots`, `treasury_actions`, `hedge_positions`, `balances`, `orders`, and `adapter_events`.
- Replace `orchestrator/app/state.py` in-memory source of truth with Postgres repositories and Redis nonce/cache helpers.
- Keep a small in-memory WebSocket fanout only for live UI subscriptions.
- Make all execution paths idempotent by external idempotency key or deterministic client order ID.

Data requirements:

- Store every submitted decision, including rejected decisions.
- Store trace commit metadata before external execution.
- Store every Polymarket order ID and link it to the pricing decision that created it.
- Store every fill by Polygon transaction hash and log index.
- Store hedge positions by venue-native ID.
- Store treasury actions with source/destination chains and settlement status.
- Store raw adapter events for audit and reprocessing.

Exit gate:

- Kill and restart the stack during a live testnet loop; no nonce replay, duplicate order, duplicate fill, or lost trace occurs.
- Rebuild dashboard state from Postgres alone.
- Redis can be flushed without corrupting durable history.

## Phase 3 - Arc contracts and trace integrity

Target: every approved decision is anchored before external execution.

Tasks:

- Deploy `BuilderRegistry` and `TraceRegistry` on Arc testnet with Foundry.
- Verify contracts on Arc explorer where tooling permits.
- Register all agent IDs and wallet addresses in `BuilderRegistry`.
- Implement `TraceRegistry.commitTrace` calls through `ArcReal`.
- Add a `verifyTrace(agent_id, decision_id)` script that fetches IPFS bytes and compares `sha256(canonical_json)` to the on-chain hash.
- Add alerting for trace pipeline failure; execution must not proceed if pin or commit fails.

Exit gate:

- A real testnet pricing decision produces an IPFS CID, Arc `TraceCommitted` event, local DB row, and successful hash verification.

## Phase 4 - Polymarket live market making

Target: real quote lifecycle with builder-code attribution.

Tasks:

- Build market discovery: top volume, tight spread, clean hedge mapping, no near-term expiry.
- Subscribe to Polymarket market WebSocket for selected markets.
- Subscribe to authenticated user stream for order status and fills.
- Implement quote replace loop: cancel stale orders, submit fresh bid/ask, back off on rate limits.
- Attach `POLY_BUILDER_CODE` to every order.
- Watch Polygon `OrderFilled` events and reconcile them with CLOB/user stream fills.
- Persist fill, fee, and inventory deltas.
- Expose builder-fee accrual and public Builder Profile link to frontend.

Risk rules:

- Pause quoting if market data heartbeat is older than 2 seconds.
- Pause quoting if spread is below configured minimum after fees.
- Pause quoting if inventory would breach `MAX_POSITION`.
- Pause quoting if trace pipeline latency exceeds the configured budget.
- Pause quoting if builder code is rejected, disabled, or absent from accepted order metadata.

Exit gate:

- At least one real or testnet `OrderFilled` event has the team's builder code and links back to a pricing decision trace.

## Phase 5 - Hedge loop

Target: fills create real inventory deltas and hedges execute without manual intervention.

Tasks:

- Add market-to-reference-asset mapping table.
- Implement hedge venue scoring: USYC margin support, funding rate, liquidity, latency, reliability.
- Implement Hyperliquid fallback with real account state, leverage setting, order placement, reduce-only close, and stop-loss monitoring.
- Add Arc-native perp adapter only if a live venue exists during the hackathon window.
- Trigger hedge decisions from fill/inventory changes, not only timer loops.
- Persist position lifecycle and PnL.
- Emergency close path can bypass reasoning trace but must still persist audit rows.

Exit gate:

- A real fill or seeded real testnet fill pushes inventory over threshold, opens a real hedge, records position state, and later closes it.

## Phase 6 - Treasury loop

Target: idle capital actively moves between USDC, USYC, Gateway balances, and venue collateral.

Tasks:

- Replace static balances with real Circle/chain/Gateway balance reads.
- Implement projected next-hour USDC demand from open orders, expected fills, pending hedges, and reserve policy.
- Implement USYC subscribe/redeem with idempotency keys and settlement polling.
- Implement Gateway Arc to Polygon and Polygon to Arc transfer flows.
- Implement CCTP fallback with degraded-latency status in the trace.
- Implement builder-fee sweep threshold from Polygon back to Arc.
- Add per-wallet spend limits and runtime circuit breakers.

Exit gate:

- Treasury executes at least one real USYC subscribe/redeem pair and one real Gateway or CCTP transfer, then the dashboard reflects the resulting balances.

## Phase 7 - trace sidecar and 0G redundancy

Target: trace bodies are durably retrievable and paid for through the real nanopayment path.

Tasks:

- Add `trace-sidecar/` TypeScript service using `@circle-fin/x402-batching`.
- Expose `POST /pin` to accept canonical bytes, pay the x402 challenge, pin content, and return CID.
- Add optional 0G Storage upload after IPFS pin succeeds.
- Store sidecar payment references and pin provider receipts in Postgres.
- Add retry with bounded backoff; never execute the underlying decision if canonical IPFS pin or Arc commit fails.

Exit gate:

- A trace can be fetched by CID after a process restart and verified against `TraceRegistry`.

## Phase 8 - public UI and observability

Target: judges and operators can see the live system, and the team can operate it safely.

Tasks:

- Decide whether to keep the static dashboard or migrate to the spec's Next.js 15 Forge UI.
- Implement Keeper Dashboard: live inventory, USYC balance, builder fees, attributed volume, traces, recent fills.
- Implement Trace Viewer at `/trace/{hash}` or `/trace/{decision_id}` with on-chain hash verification.
- Implement Agent Inspector with live structured output per agent.
- Implement Demo Mode using captured real testnet/mainnet artifacts.
- Add Prometheus metrics: quote latency, trace latency, order acceptance rate, fill rate, hedge latency, treasury latency, Gateway latency, adapter error count, balance by chain.
- Add Grafana dashboard and alert thresholds.

Exit gate:

- Public URL shows live state.
- Trace viewer proves at least 10 traces end-to-end.
- Demo replay links to real external artifacts.

## Phase 9 - testnet burn-in

Target: continuous operation before mainnet funds are at risk.

Burn-in script:

1. Run 3 to 5 markets on testnet/shadow mode for 2 hours.
2. Confirm no duplicate nonces, duplicate order IDs, or missing traces.
3. Force one trace pin failure and confirm execution stops.
4. Force one Polymarket rate-limit response and confirm quote cadence backs off.
5. Force one stale orderbook heartbeat and confirm quoting pauses.
6. Force one hedge threshold breach and confirm hedge execution.
7. Force one Gateway timeout and confirm CCTP fallback or degraded status.
8. Restart all services mid-loop and confirm recovery.

Exit gate:

- Two-hour burn-in produces a clean incident log and all external artifact links resolve.

## Phase 10 - mainnet rollout

Target: controlled bankroll, public attribution, and measurable traction.

Rollout:

- Start with a small bankroll and 3 to 5 low-risk markets.
- Increase only after accepted orders, fills, traces, hedges, and treasury actions reconcile cleanly.
- Expand toward 30 to 50 markets only after rate-limit and inventory behavior is understood.
- Keep mainnet quoting disabled by one global kill switch and per-agent kill switches.
- Export daily evidence: builder profile volume, fee accrual, order-filled txs, Arc trace commits, USYC actions, Gateway transfers.

Success gate:

- 100 attributed fills or the strongest available testnet equivalent if builder admission is delayed.
- Public dashboard and trace viewer are stable.
- Submission package has click-through evidence for OrderFilled, hedge, treasury rebalance, and trace verification.

## Implementation order by repo area

1. `config`: typed live settings, secrets, stale Arc defaults, kill switches.
2. `adapters/real`: Arc, wallets/signing, Polymarket, Gateway, USYC, nanopayment sidecar, Hyperliquid.
3. `orchestrator`: Postgres/Redis repositories, idempotency, execution recovery, event reconciliation.
4. `contracts`: deploy scripts, verification script, agent registration script.
5. `agents`: event-driven pricing, hedge, and treasury loops with real state reads.
6. `trace-sidecar`: x402/Gateway nanopayment pinning and optional 0G upload.
7. `frontend`: live dashboard, trace viewer, agent inspector, captured-artifact demo mode.
8. `ops`: Docker Compose with Postgres, Redis, Caddy, Prometheus, Grafana, secrets, runbooks.

## First five pull requests

PR 1 - Live configuration and database foundation:

- Add typed settings, `.env.example` expansion, Postgres/Redis compose services, migrations, repository interfaces, and durable nonce handling.

PR 2 - Arc and trace pipeline live path:

- Add `ArcReal`, deploy/register scripts, `TraceRegistry` commit wiring, real trace verification script, and tests around canonical hash parity.

PR 3 - Polymarket V2 live path:

- Add `PolymarketReal`, WebSocket market/user ingestion, builder-code order submission, order/fill persistence, and quote pause/backoff controls.

PR 4 - Circle treasury path:

- Add wallets, Gateway, USYC, CCTP fallback, balance reconciliation, and treasury action settlement tracking.

PR 5 - Hedge and operator visibility:

- Add Hyperliquid real adapter, hedge trigger/reconcile loop, live dashboard fields, trace viewer verification, and burn-in scripts.

## Non-negotiable safety invariants

- Pin and commit trace before execution for pricing, hedge open/close, and treasury actions.
- Never submit an order unless the builder code is present in the signed payload.
- Never retry an external write without an idempotency key or deterministic client order ID.
- Never trust WebSocket alone; reconcile with REST/on-chain events.
- Never treat an in-memory state value as durable truth.
- Never run mainnet without kill switches and wallet-level spend limits.
- Never allow direct raw ERC-20 transfer into Gateway wallet contracts.
- Never assume USYC eligibility; verify before production use.

## What can remain mocked

For the live path, nothing in the execution, trace, treasury, hedge, or persistence path should be mocked.

Allowed non-live mocks:

- Unit tests.
- Local UI development.
- Demo replay based on captured real artifacts.
- A disabled-by-default shadow adapter used only for comparing live strategy decisions against historical data.

## Done checklist

- `MOCK_MODE=0 docker compose up` starts all services.
- `/health` reports all live adapters healthy.
- A pricing decision creates a real trace, real Arc commit, real Polymarket order, and real persisted order row.
- A fill updates inventory and links to a Polygon transaction with the builder code.
- A hedge opens and closes on a real venue.
- Treasury executes USYC and cross-chain balance movement where eligibility/support allows.
- Dashboard updates from Postgres/WebSocket live state.
- Trace viewer verifies hash against Arc and IPFS.
- Restart recovery is clean.
- Submission evidence links are collected daily.


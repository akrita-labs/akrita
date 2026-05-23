# AKRITA — Architecture

## 1. System topology

```
                       ┌─────────────────────────────────────────────┐
                       │     Polymarket V2 (Polygon mainnet)         │
                       │  ┌──────────┐         ┌──────────────────┐  │
                       │  │  CLOB    │────────▶│  Builder         │  │
                       │  │  feed    │         │  attribution     │  │
                       │  └─────┬────┘         └──────────┬───────┘  │
                       └────────┼─────────────────────────┼──────────┘
                                │                         │
                       quotes,  ▼     OrderFilled         ▼  USDC builder fees
                       fills          (bytes32 builder)
   ┌──────────────────────────────────────────────────────────────────┐
   │                  AKRITA keeper (Docker, single host)             │
   │                                                                  │
   │   ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
   │   │  NOMOS   │    │  SPATHA  │    │  AGROS   │                   │
   │   │  pricing │    │  hedge   │    │  treasury│                   │
   │   └────┬─────┘    └────┬─────┘    └────┬─────┘                   │
   │        │ POST           │ POST          │ POST                   │
   │        │ /decisions/    │               │                        │
   │        └────────────────┴────────┬──────┘                        │
   │                                  ▼                               │
   │                ┌──────────────────────────────┐                  │
   │                │  Orchestrator BFF (FastAPI)  │                  │
   │                │  • nonce replay check        │                  │
   │                │  • RiskAgent (12 checks)     │                  │
   │                │  • trace pipeline            │                  │
   │                │  • execute through adapter   │                  │
   │                └─┬──────────────────────────┬─┘                  │
   │                  │                          │                    │
   │                  ▼                          ▼                    │
   │           ┌──────────────┐         ┌────────────────┐            │
   │           │  Adapters    │         │  WebSocket /   │            │
   │           │  (external)  │         │  state for UI  │            │
   │           └──────────────┘         └────────────────┘            │
   └──────────────────────────────────────────────────────────────────┘
              │            │                  │
              ▼            ▼                  ▼
   ┌──────────────┐  ┌──────────┐    ┌──────────────────┐
   │   Circle     │  │  IPFS    │    │   Hyperliquid    │
   │   Wallets    │  │  (Nano-  │    │   testnet perps  │
   │   API        │  │  payment)│    │                  │
   └──────┬───────┘  └─────┬────┘    └──────────────────┘
          │                │
          ▼                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                       Arc L1 (testnet)                           │
   │   ┌──────────────────┐  ┌──────────────────┐                     │
   │   │ TraceRegistry    │  │ BuilderRegistry  │                     │
   │   │ (commits per     │  │ (agent ↔ builder │                     │
   │   │  decision)       │  │  code mapping)   │                     │
   │   └──────────────────┘  └──────────────────┘                     │
   │                                                                  │
   │   ┌──────────────────────────────────────────────────────────┐   │
   │   │  Circle primitives (native):                             │   │
   │   │  • USDC (gas + working capital)                          │   │
   │   │  • USYC Teller (subscribe/redeem)                        │   │
   │   │  • Gateway (Arc ↔ Polygon in <500ms)                     │   │
   │   │  • Paymaster (USDC-denominated gas)                      │   │
   │   └──────────────────────────────────────────────────────────┘   │
   └──────────────────────────────────────────────────────────────────┘
```

## 2. Decision lifecycle (per quote)

```
1. Market event (orderbook delta, fill, news)
       │
       ▼
2. NOMOS computes target (microprice → inventory skew → LLM calibrate → clamp)
       │
       ▼
3. POST /decisions/pricing { schema_version, decision_id, nonce, rationale_hash, ... }
       │
       ▼
4. Orchestrator:
   (a) nonce replay check (Redis SETNX with 1h TTL)
   (b) RiskAgent.evaluate() — 12 deterministic boolean checks
   (c) if rejected → persist + 200 with status=rejected; no trace, no execution
   (d) if approved → build TraceBody { fundamentals, technical, conclusion, risk_gate }
       │
       ▼
5. canonical_json(TraceBody) → sha256 → trace_hash
       │
       ▼
6. Nanopayment.pin_to_ipfs(body_bytes) → ipfs_cid  ($0.001 USDC)
       │
       ▼
7. TraceRegistry.commitTrace(agentId, decisionId, hash, cid) on Arc  (~$0.01)
       │
       ▼
8. Polymarket V2 .submit_quote(bid, ask, builderCode) on Polygon
       │
       ▼
9. WebSocket broadcast → dashboard updates KPIs + agent feed
       │
       ▼
10. (eventually) OrderFilled emits with our builderCode → fee accrues
                  Inventory updated → SPATHA loop sees breach → hedge fires
```

The pin + commit must succeed BEFORE the order submits. Trace anchors precede action, not the other way around. This is what makes the reasoning verifiable post-facto.

## 3. Why-only-Arc economics

| Factor | Ethereum L1 | Base / Polygon L2 | Arc testnet/mainnet |
|---|---|---|---|
| Per-trace commit cost | $5–$20 | $0.10–$0.50 | ~$0.01 |
| USDC ↔ USYC settlement | min (bridge) | sec (native) | sub-second (native) |
| Gateway Arc ↔ Polygon | n/a | n/a | <500ms |
| Decisions per day before fees > yield carry | 10–20 | 200–500 | 5,000+ |

At Arc's price point, the keeper can rebalance USYC↔USDC on every quote update without erosion. On Base, the rebalance cadence has to be amortized across 5–10 quote updates. On Ethereum L1, the entire thesis is uneconomical at retail size.

## 4. State persistence

The prototype uses an **in-memory `StateStore`** singleton:

- `decisions[(agent_role, decision_id)]` — keyed by composite so agents' independent counters don't collide
- `nonces` — set of `(role, nonce)` tuples
- `traces[decision_id]` — commit metadata
- `inventory[market_id]` — latest snapshot per market
- `fills` — append-only list of `OrderFilled` events
- `hedge_positions[position_id]` — open + closed
- `treasury_actions` — append-only log of USYC/Gateway moves

For production, replace `state.py` with a Postgres-backed implementation. The interface is small enough that the swap is a single PR. Schemas to use:

```sql
CREATE TABLE decisions (
    agent_role TEXT NOT NULL,
    decision_id BIGINT NOT NULL,
    payload_jsonb JSONB NOT NULL,
    nonce BIGINT NOT NULL,
    risk_passed BOOLEAN NOT NULL,
    trace_hash BYTEA,
    arc_tx_hash BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_role, decision_id),
    UNIQUE (agent_role, nonce)
);
-- + fills, hedge_positions, treasury_actions, traces (mirror StateStore fields)
```

## 5. Component responsibility matrix

| Component | Owns | Reads from | Writes to |
|---|---|---|---|
| NOMOS | Pricing decisions | Polymarket orderbook (read-only), Orchestrator `/state/inventory` | Orchestrator `/decisions/pricing` |
| SPATHA | Hedge open/close | Orchestrator `/state/inventory`, Hyperliquid funding | Orchestrator `/decisions/hedge` |
| AGROS | USDC ⇄ USYC ⇄ Gateway routing | Orchestrator `/state/balances`, projected outflows | Orchestrator `/decisions/treasury` |
| Orchestrator | Risk gate, trace pipeline, execution, state | Agents (decisions), adapters (execute), all primitives | State store, broadcasts |
| RiskAgent | 12 deterministic checks per decision type | Decision payload + context (`now_ms`) | RiskGateResult |
| TracePipeline | Pin to IPFS, hash, commit on Arc | Decision, risk result, contextual sections | IPFS, Arc TraceRegistry, state store |
| Adapters | External I/O (Circle, Polymarket, HL, Arc) | Real APIs | External services |

## 6. Failure modes and degradations

| Failure | Impact | Mitigation in code |
|---|---|---|
| Orchestrator unreachable | Agents log + retry | `httpx` 10s timeout + exception caught in `submit()` |
| IPFS pin fails | Decision rejected before execution | Trace pipeline raises; orchestrator returns 500 |
| Risk gate rejects | Decision logged with reason, NOT executed | `status: "rejected"` response, persisted to state |
| Nonce replay | Decision rejected with 409 | `state.claim_nonce()` atomic SETNX semantics |
| Polymarket relayer slow | Decision in flight; next agent tick computes fresh quote | Stateless agent loop — no in-flight state to recover |
| USYC redeem latency | AGROS holds back on subscribe until queue clears | `SAFETY_MULTIPLIER` knob (default 1.5x projected outflow) |
| Arc finality lag | Trace commit blocks for ~1s | `submit_tx` has `await asyncio.sleep` capped at 5s |

## 7. The 30-second demo flow

```
t=0s   POST /demo/run    →  NOMOS quote (bid 0.605, ask 0.635, size 100)
                            → trace pinned → commit on Arc → quote on Polymarket
t=2s   simulated fill   →  OrderFilled emitted, builder fee accrued
t=4s   SPATHA fires     →  short BTC-PERP 0.05 with 250 USDC margin on HL
                            → trace pinned → commit on Arc → position open
t=6s   AGROS sweeps     →  USYC subscribe 500 USDC
                            → trace pinned → commit on Arc → USYC balance up
```

In the live demo, judges see this same chain on the dashboard, with click-through to:
- Polygonscan tx (OrderFilled with our `builderCode` in the indexed param)
- Arc Explorer tx (TraceRegistry commit)
- IPFS body (verifiable sha256 match)
- HL position page
- USYC NAV ticker incrementing in real time

Every artifact is third-party verifiable. None of it depends on trusting the team.

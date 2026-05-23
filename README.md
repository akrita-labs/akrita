# AKRITA

AKRITA is a multi-agent keeper prototype for Polymarket V2. Three agents coordinate through a FastAPI orchestrator:

- `NOMOS` prices markets and submits quote updates
- `SPATHA` hedges inventory on Hyperliquid
- `AGROS` manages treasury flow between USDC and USYC

Every approved decision is pinned to IPFS, hashed canonically, and committed to Arc before the underlying execution happens.

## Stack

- `orchestrator/`: FastAPI BFF, risk gate, trace pipeline, state, demo routes
- `agents/`: autonomous NOMOS, SPATHA, and AGROS workers
- `adapters/`: integration adapters for Arc, Circle, Polymarket, Hyperliquid, and IPFS pinning
- `shared/`: canonical serialization and shared Pydantic models
- `contracts/`: Arc smart contracts for trace and builder registration
- `frontend/`: bundled demo dashboard
- `docs/`: architecture, integration notes, and brand direction

## Quickstart

1. Create a local environment file from `.env.example`.
2. Run `pip install -e ".[dev]"` for local development, or `docker compose up --build` for the full stack.
3. Start the demo flow with `make demo` once the orchestrator is running.

Useful targets:

- `make test`
- `make lint`
- `make run`
- `make run-detached`
- `make stop`
- `make contracts-test`

## Demo flow

The built-in demo exercises the full lifecycle:

1. NOMOS submits a pricing decision
2. The orchestrator risk-checks it and commits the trace
3. A fill is simulated with builder attribution
4. SPATHA opens a hedge
5. AGROS subscribes idle USDC into USYC

## Live integrations

For wiring real adapters and deployment sequencing, see:

- `docs/ARCHITECTURE.md`
- `docs/INTEGRATION.md`

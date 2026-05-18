# AKRITA

AKRITA is a multi-agent keeper for Polymarket V2. Three agents coordinate through a FastAPI orchestrator:

- `NOMOS` prices markets and submits quote updates
- `SPATHA` hedges inventory on a perp venue
- `AGROS` manages treasury flow between USDC and USYC

Every approved decision is pinned to IPFS, hashed canonically, and committed to Arc before the underlying execution happens.

AKRITA runs against live integrations only — there is no mock path.

## Stack

- `orchestrator/`: FastAPI BFF, risk gate, trace pipeline, state
- `agents/`: autonomous NOMOS, SPATHA, and AGROS workers
- `adapters/`: protocol definitions (`adapters/base.py`); live clients in `adapters/real/`
- `shared/`: canonical serialization and shared Pydantic models
- `contracts/`: Arc smart contracts for trace and builder registration
- `frontend/`: live keeper dashboard and trace viewer
- `docs/`: architecture, integration notes, the live implementation plan, and brand direction

## Status

The live adapter layer is not yet wired — `get_adapters()` raises until `adapters/real/`
is implemented. See `docs/LIVE_IMPLEMENTATION_PLAN.md` Phase 1 for the build order and
exit gates. Until then the decision pipeline cannot run end-to-end.

## Quickstart

1. Create a local environment file from `.env.example` and fill in real credentials for every external surface.
2. Run `pip install -e ".[dev]"` for local development, or `docker compose up --build` for the full stack.

Useful targets:

- `make test`
- `make lint`
- `make run`
- `make run-detached`
- `make stop`
- `make contracts-test`

## Live integration

For integration sequencing and deployment, see:

- `docs/LIVE_IMPLEMENTATION_PLAN.md`
- `docs/ARCHITECTURE.md`
- `docs/INTEGRATION.md`

# AKRITA — working notes for Claude Code

Multi-tenant autonomous keeper for Polymarket V2, settling on Arc. Three signed agents
(NOMOS pricing, SPATHA hedging, AGROS treasury) gated by a deterministic Risk Agent;
every decision is committed as a verifiable reasoning trace (canonical JSON → sha256 →
IPFS via Circle Nanopayments → on-chain TraceRegistry on Arc).

## Environment / conventions
- Python is always `.venv/bin/python` (3.12). Tests: `.venv/bin/python -m pytest -q`.
- Foundry `forge` is at `/home/ubuntu/.foundry/bin/forge`; contracts in `contracts/` (chainId 5042002).
- Lint: `.venv/bin/ruff check`. Migrations: `.venv/bin/alembic` from repo root.
- Active branch for v1 work: `feat/akrita-v1-depuration`. Commit only when asked; never commit `.env` or `secrets/` (gitignored).

## Live deployment (this host)
- Native systemd **`akrita-orchestrator`** (uvicorn 127.0.0.1:8000) behind **Caddy** → https://akritafi.xyz, with **host** Postgres + Redis (the `.env` DSN `localhost:5432` is the LIVE DB).
- `docker-compose.yml` is **dev-only** — do not run it on the live host (port clash with host PG/Redis).
- The 3 agents are **not** running as systemd units yet; only the orchestrator + Caddy are.
- Live order/hedge/treasury writes are gated on external funding (Polymarket pUSD collateral, Hyperliquid margin, USYC allowlist). The decision + trace + attribution path is fully live regardless.

## Operator skills (`.claude/skills/`)
Run a repo runbook with `/akrita-…`. **Safe (read-only):** `akrita-nomos-sim`,
`akrita-usyc-allowlist-check`, `akrita-stack` (status). **Gated** (explicit invoke +
confirmation token, never auto-run): `akrita-stack` (restart → `RESTART-CONFIRMED`),
`akrita-alembic-migrate` → `MIGRATE-CONFIRMED`, `akrita-register-builder-code` →
`REGISTER-CONFIRMED`, `akrita-deploy-arc-contracts` → `DEPLOY-CONFIRMED-<network>`,
`akrita-kill-switch` → `KILL-CONFIRMED`. Each skill has the real commands; prefer them
over reconstructing runbooks from memory.

## Boundaries
- Agents place trades / move treasury **in code, behind the Risk Agent** — never via a
  skill. Skills are operator tooling, not the trading path.
- `allowed-tools` in SKILL.md does not enforce restrictions; real safety = commands not
  in the allow-list (so they prompt) + the in-body confirmation tokens above.
- Circle skills are already installed (`circle-skills@circle`). Do not clone external
  community skill repos — confirmed malware vector.

#!/usr/bin/env python3
"""Seed the multi-tenant platform with operators + per-user builder codes.

Drives the *real* onboarding endpoints over HTTP (POST /api/users then
POST /api/builder), so running it exercises the whole stack end-to-end and
leaves verifiable on-chain BuilderRegistry registrations behind.

  - The primary operator is assigned the real Polymarket builder code from
    POLY_BUILDER_CODE (already on-chain as agent 1 — onboarding adopts it).
  - The rest get deterministic bytes32 demo codes (keccak of the handle) and
    are registered fresh on the BuilderRegistry (agentId 100+).

Idempotent: re-running reuses existing users (handle is unique) and never
re-registers an already-on-chain code.

Usage:
    .venv/bin/python scripts/bootstrap/seed_operators.py [--count N]
        [--base-url http://localhost:8000] [--no-register]
"""
from __future__ import annotations

import argparse
import sys

import httpx
from web3 import Web3

from shared.config import settings

# Curated operators. The first is the real operator (keeps the live code);
# the rest are demo operators onboarded to prove the multi-tenant flow.
OPERATORS: list[tuple[str, str]] = [
    ("operator", "AKRITA House"),
    ("theodora-capital", "Theodora Capital"),
    ("komnenos-research", "Komnenos Research"),
    ("porphyry-labs", "Porphyry Labs"),
    ("nikephoros-td", "Nikephoros Trading"),
    ("anna-quant", "Anna Quant"),
    ("basil-systematic", "Basil Systematic"),
    ("justinian-mkts", "Justinian Markets"),
    ("palaiologos-fund", "Palaiologos Fund"),
    ("belisarius-arb", "Belisarius Arb"),
    ("zoe-strategies", "Zoe Strategies"),
    ("romanos-desk", "Romanos Desk"),
]


def demo_code(handle: str) -> str:
    h = Web3.keccak(text=f"akrita:builder:{handle}").hex()  # hexbytes 1.x drops the 0x
    return h if h.startswith("0x") else "0x" + h


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=settings.orchestrator_url)
    ap.add_argument("--count", type=int, default=len(OPERATORS))
    ap.add_argument("--no-register", action="store_true", help="store codes but skip on-chain registration")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    ops = OPERATORS[: max(1, min(args.count, len(OPERATORS)))]

    with httpx.Client(base_url=base, timeout=180.0) as client:
        # Map existing users by handle so re-runs are idempotent.
        existing = {u["handle"]: u for u in client.get("/api/users").json().get("users", [])}

        print(f"Seeding {len(ops)} operators against {base}\n")
        for i, (handle, display) in enumerate(ops):
            code = settings.poly_builder_code if i == 0 and settings.poly_builder_code else demo_code(handle)

            if handle in existing:
                user = existing[handle]
                print(f"· @{handle:18s} exists  ({user['id'][:8]})")
            else:
                r = client.post("/api/users", json={"handle": handle, "display_name": display})
                if r.status_code >= 400:
                    print(f"✗ @{handle:18s} create failed: {r.status_code} {r.text}")
                    continue
                user = r.json()
                print(f"+ @{handle:18s} created ({user['id'][:8]})")

            r = client.post(
                "/api/builder",
                json={
                    "user_id": user["id"],
                    "builder_code": code,
                    "auto_register": not args.no_register,
                },
            )
            if r.status_code >= 400:
                print(f"    builder register failed: {r.status_code} {r.text}")
                continue
            v = r.json()
            tag = "REAL" if (i == 0 and code == settings.poly_builder_code) else "demo"
            print(
                f"    [{tag}] agent={v.get('onchain_agent_id')} "
                f"status={v.get('registration_status')} "
                f"match={v.get('onchain_matches')} code={code[:14]}…"
            )

    print("\nDone. Public board: " + base + "/leaderboard")
    return 0


if __name__ == "__main__":
    sys.exit(main())

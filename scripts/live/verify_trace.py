"""
Trace verification — the end-to-end integrity proof.

Two modes:

  1. Verify an existing commit (default):
       .venv/bin/python scripts/live/verify_trace.py <agent_id> <decision_id>
     Fetches the IPFS body by the on-chain CID, recomputes sha256 over the
     canonical bytes, and confirms it matches both the stored on-chain hash
     and the contract's own verifyTrace() result.

  2. Full round-trip smoke (--commit):
       .venv/bin/python scripts/live/verify_trace.py --commit
     Builds a sample trace body, pins it to IPFS, commits to TraceRegistry on
     Arc via the Circle trace-keeper, then verifies — proving the whole
     pipeline end to end.

Exit 0 on success, non-zero on any mismatch.
"""
from __future__ import annotations

import asyncio
import sys
import time

from adapters import get_adapters
from shared.canonical import canonical_json, trace_hash
from shared.config import settings


async def verify_existing(agent_id: int, decision_id: int) -> int:
    a = get_adapters()
    commit = await a.arc.get_trace_commit(agent_id, decision_id)
    if commit is None:
        print(f"✗ no on-chain commit for agent={agent_id} decision={decision_id}")
        return 1

    print("on-chain commit:")
    print(f"  trace_hash: {commit['trace_hash']}")
    print(f"  ipfs_cid:   {commit['ipfs_cid']}")
    print(f"  timestamp:  {commit['timestamp']}")

    body = await a.nanopayment.fetch_from_ipfs(commit["ipfs_cid"])
    if body is None:
        print(f"✗ could not fetch IPFS body for CID {commit['ipfs_cid']}")
        return 1
    print(f"  fetched {len(body)} bytes from IPFS")

    local_hash = trace_hash_from_bytes(body)
    print(f"\nrecomputed sha256(body): {local_hash}")
    match_stored = local_hash.lower() == commit["trace_hash"].lower()
    print(f"  matches on-chain stored hash: {'✓' if match_stored else '✗'}")

    onchain_ok = await a.arc.verify_trace_onchain(agent_id, decision_id, body)
    print(f"  contract verifyTrace():       {'✓' if onchain_ok else '✗'}")

    ok = match_stored and onchain_ok
    print(f"\n{'✓ VERIFIED' if ok else '✗ MISMATCH'}")
    return 0 if ok else 1


def trace_hash_from_bytes(body: bytes) -> str:
    import hashlib
    return "0x" + hashlib.sha256(body).hexdigest()


async def commit_and_verify() -> int:
    """Full pipeline round-trip with a sample body."""
    a = get_adapters()
    agent_id = 1  # NOMOS
    decision_id = int(time.time())  # unique-ish so re-runs don't collide

    body_obj = {
        "schema_version": "akrita/trace/v1",
        "agent": "nomos",
        "decision_id": decision_id,
        "kind": "verify_trace_smoke",
        "fundamentals": {"note": "end-to-end trace pipeline smoke"},
        "ts_ms": int(time.time() * 1000),
    }
    body_bytes = canonical_json(body_obj)
    expected_hash = trace_hash(body_obj)
    print(f"sample body ({len(body_bytes)} bytes), sha256={expected_hash}")
    print(f"agent_id={agent_id} decision_id={decision_id}")

    cid = await a.nanopayment.pin_to_ipfs(body_bytes)
    print(f"pinned to IPFS: {cid}")

    print("committing to TraceRegistry on Arc (via Circle trace-keeper)…")
    tx = await a.arc.commit_trace(agent_id, decision_id, expected_hash, cid)
    print(f"  arc tx: {tx.tx_hash}  block: {tx.block_number}  status: {tx.status}")

    print("\n--- verifying ---")
    return await verify_existing(agent_id, decision_id)


def main() -> int:
    if not settings.trace_registry_addr:
        print("TRACE_REGISTRY_ADDR not set — deploy contracts first")
        return 2
    if "--commit" in sys.argv:
        return asyncio.run(commit_and_verify())
    if len(sys.argv) >= 3:
        return asyncio.run(verify_existing(int(sys.argv[1]), int(sys.argv[2])))
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())

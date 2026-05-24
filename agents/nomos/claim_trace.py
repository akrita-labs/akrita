"""
NOMOS — rug-risk claim reasoning-trace builder (deterministic, import-safe).

Turns a structured blacklist-addition record (see nfi_watcher.build_claim_record)
into the canonical reasoning-trace body that gets hashed (sha256 of canonical
JSON) and anchored on Arc via the existing trace pipeline / TraceRegistry, then
referenced by ClaimRegistry.issueClaim(traceHash, ipfsCid, ...).

The body mirrors the existing TraceBody section structure (fundamentals /
technical / conclusion) so the trace viewer and verifier work unchanged.
"""
from __future__ import annotations

from shared.canonical import trace_hash


def build_claim_trace(record: dict, *, credibility: float, decision_id: int) -> dict:
    """Canonical reasoning-trace body for a rug-risk claim.

    `credibility` in [0,1] is NOMOS's read on how strongly the NFI signal implies
    rug risk (source reputation × signal strength); recorded, not yet a gate.
    """
    window_days = max(1, record["window_s"] // 86400)
    drop_pct = record["drop_threshold_bps"] / 100.0
    return {
        "schema_version": "akrita/trace/v1",
        "decision_id": decision_id,
        "agent_role": "nomos",
        "decision_type": "rug_claim",
        "fundamentals": {
            "source": {
                "repo": record["source_repo"],
                "file": record["source_file"],
                "commit": record["source_commit"],
            },
            "token": record["token"],
            "pair": record["pair"],
            "exchange": record["exchange"],
        },
        "technical": {
            "signal": "nfi_blacklist_addition",
            "credibility": round(float(credibility), 4),
            "window_s": record["window_s"],
            "drop_threshold_bps": record["drop_threshold_bps"],
        },
        "conclusion": {
            "action": "issue_rug_claim",
            "token_id": record["token_id"],
            "statement": (
                f"{record['token']} added to NFI {record['exchange']} blacklist at "
                f"{record['source_commit'][:10]} — rug risk: predict >{drop_pct:.0f}% "
                f"drop within {window_days}d"
            ),
        },
    }


def claim_trace_hash(body: dict) -> str:
    """0x-prefixed sha256 of the canonical trace body — the value ClaimRegistry references."""
    return trace_hash(body)

"""
NOMOS — rug-risk claim reasoning-trace builder (deterministic, import-safe).

Turns a GoPlus screen record (see goplus_screen.build_claim_record) into the
canonical reasoning-trace body that gets hashed (sha256 of canonical JSON),
pinned to IPFS, and anchored on Arc via TraceRegistry, then referenced by
ClaimRegistry.issueClaim(traceHash, ipfsCid, ...).

The body mirrors the existing TraceBody section structure (fundamentals /
technical / conclusion) so the trace viewer and verifier work unchanged. The
GoPlus response hash is the provenance: anyone can re-query GoPlus and reproduce
the flags + hash.
"""
from __future__ import annotations

from shared.canonical import trace_hash


def build_claim_trace(record: dict, *, decision_id: int) -> dict:
    """Canonical reasoning-trace body for a GoPlus-sourced rug-risk claim."""
    window_days = max(1, record["window_s"] // 86400)
    drop_pct = record["drop_threshold_bps"] / 100.0
    reasons = record.get("reasons", [])
    return {
        "schema_version": "akrita/trace/v1",
        "decision_id": decision_id,
        "agent_role": "nomos",
        "decision_type": "rug_claim",
        "fundamentals": {
            "source": {
                "provider": "goplus",
                "chain_id": record["chain_id"],
                "address": record["address"],
                "provenance": record["provenance"],
            },
            "token": record["token"],
            "token_name": record.get("token_name", ""),
        },
        "technical": {
            "signal": "goplus_token_security",
            "reasons": reasons,
            "severity": record.get("severity", len(reasons)),
            "flags": record.get("flags", {}),
            "window_s": record["window_s"],
            "drop_threshold_bps": record["drop_threshold_bps"],
        },
        "conclusion": {
            "action": "issue_rug_claim",
            "token_id": record["token_id"],
            "statement": (
                f"{record['token']} flagged by GoPlus ({', '.join(reasons) or 'risk'}) — "
                f"rug risk: predict >{drop_pct:.0f}% drop within {window_days}d"
            ),
        },
    }


def claim_trace_hash(body: dict) -> str:
    """0x-prefixed sha256 of the canonical trace body — the value ClaimRegistry references."""
    return trace_hash(body)

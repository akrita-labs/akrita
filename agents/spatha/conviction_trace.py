"""
SPATHA — bond-conviction reasoning trace (deterministic, import-safe).

SPATHA reads NOMOS's IPFS-pinned reasoning for an issued claim, forms its own
judgment (back / fade / abstain), and anchors THIS trace on Arc as agent 2 — a
second, independent on-chain decision about the same claim. The body mirrors the
NOMOS trace sections so the viewer/verifier work unchanged.
"""
from __future__ import annotations

from shared.canonical import trace_hash


def build_conviction_trace(
    claim: dict,
    nomos_summary: dict,
    conviction: dict,
    plan: dict,
    *,
    decision_id: int,
) -> dict:
    """Canonical reasoning-trace body for a SPATHA bond-conviction decision."""
    return {
        "schema_version": "akrita/trace/v1",
        "decision_id": decision_id,
        "agent_role": "spatha",
        "decision_type": "bond_conviction",
        "fundamentals": {
            "claim_ref": {
                "claim_id": claim.get("claim_id"),
                "token_id": claim.get("token_id"),
                "nomos_trace_hash": claim.get("trace_hash"),
            },
            "nomos_view": {
                "token": nomos_summary.get("token"),
                "severity": nomos_summary.get("severity"),
                "nomos_confidence": nomos_summary.get("nomos_confidence"),
                "reasons": nomos_summary.get("reasons", []),
            },
        },
        "technical": {
            "signal": "bond_conviction",
            "position": plan.get("position"),
            "amount_usdc": plan.get("amount_usdc"),
            "execution": plan.get("execution", "decided"),
        },
        "conclusion": {
            "action": plan.get("action", "none"),
            "position": plan.get("position"),
            "amount_usdc": plan.get("amount_usdc", 0.0),
            "statement": _statement(claim, nomos_summary, plan),
            "rationale": conviction.get("rationale"),
        },
        "reasoning": {
            "decided_by": conviction.get("decided_by"),
            "model": conviction.get("model"),
            "conviction": conviction.get("conviction"),
            "rationale": conviction.get("rationale"),
            "latency_ms": conviction.get("latency_ms"),
        },
    }


def _statement(claim: dict, nomos_summary: dict, plan: dict) -> str:
    token = nomos_summary.get("token") or f"claim #{claim.get('claim_id')}"
    if plan.get("action") != "stake":
        return f"SPATHA abstained on {token} — conviction below the staking floor."
    side = "backs" if plan.get("backs_claim") else "fades"
    return (
        f"SPATHA {side} the rug call on {token}: stake ${plan.get('amount_usdc', 0):.2f} USDC "
        f"({'token rugs' if plan.get('backs_claim') else 'token holds'})."
    )


def conviction_trace_hash(body: dict) -> str:
    return trace_hash(body)

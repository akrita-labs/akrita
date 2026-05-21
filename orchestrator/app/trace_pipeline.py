"""
AKRITA trace pipeline.

For each decision: build a TraceBody (Trading-R1 schema), pin the
canonical-JSON-encoded body to IPFS via Nanopayment, commit the
sha256 + CID to TraceRegistry on Arc.

The whole pipeline runs BEFORE the underlying execution (Polymarket
order submit, USYC subscribe, etc.). If trace pinning fails, the
decision is rejected. This guarantees on-chain reasoning anchor
predates the action — no post-hoc rationalization possible.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from adapters import get_adapters
from shared.canonical import canonical_json, trace_hash
from shared.config import settings
from shared.models import (
    AgentRole,
    HedgeDecision,
    PricingDecision,
    RiskGateResult,
    TraceBody,
    TreasuryDecision,
)


@dataclass
class TraceCommit:
    decision_id: int
    agent_role: str
    trace_hash: str
    ipfs_cid: str
    arc_tx_hash: str
    arc_block: int
    body_size_bytes: int


class TracePipeline:
    """Pin → hash → commit lifecycle."""

    def __init__(self, trace_registry_addr: str):
        self.trace_registry_addr = trace_registry_addr

    async def commit(
        self,
        decision,
        risk_result: RiskGateResult,
        fundamentals: dict[str, Any],
        technical: dict[str, Any],
        conclusion: dict[str, Any],
    ) -> TraceCommit:
        """Run full pipeline. Raises if any step fails."""
        adapters = get_adapters()

        decision_type = self._decision_type(decision)

        body = TraceBody(
            decision_id=decision.decision_id,
            agent_role=decision.agent_role,
            decision_type=decision_type,
            fundamentals=fundamentals,
            technical=technical,
            conclusion=conclusion,
            risk_gate=risk_result,
            model=settings.akrita_reasoner_model or "unset",
            computation_ms=0,
            ts_ms=int(time.time() * 1000),
        )

        # 1. Canonicalize and hash
        body_dict = body.model_dump(mode="json")
        body_bytes = canonical_json(body_dict)
        body_hash = trace_hash(body_dict)

        # 2. Pin to IPFS via Nanopayment
        cid = await adapters.nanopayment.pin_to_ipfs(body_bytes)

        # 3. Commit (agentId, decisionId, sha256 hash, CID) to TraceRegistry on
        #    Arc. ArcReal signs via the Circle MPC trace-keeper wallet and
        #    encodes the call from the ABI signature — no manual calldata.
        tx = await adapters.arc.commit_trace(
            agent_id=self._agent_id(decision.agent_role),
            decision_id=decision.decision_id,
            trace_hash_hex=body_hash,
            ipfs_cid=cid,
        )

        return TraceCommit(
            decision_id=decision.decision_id,
            agent_role=decision.agent_role,
            trace_hash=body_hash,
            ipfs_cid=cid,
            arc_tx_hash=tx.tx_hash,
            arc_block=tx.block_number,
            body_size_bytes=len(body_bytes),
        )

    def _decision_type(self, d) -> str:
        if isinstance(d, PricingDecision):
            return "polymarket_quote_update"
        if isinstance(d, HedgeDecision):
            return f"hedge_{d.action}"
        if isinstance(d, TreasuryDecision):
            return f"treasury_{d.action}"
        return "unknown"

    def _agent_id(self, role: str) -> int:
        """Map agent role enum value to BuilderRegistry agent ID."""
        # In real deployment, read from BuilderRegistry contract
        return {
            AgentRole.NOMOS.value: 1,
            AgentRole.SPATHA.value: 2,
            AgentRole.AGROS.value: 3,
        }.get(role, 0)

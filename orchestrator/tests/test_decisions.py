"""Integration test for the demo flow via FastAPI TestClient.

This is the most important test in the repo: it proves the entire
decision lifecycle (risk gate → trace pin → on-chain commit → execute)
works end-to-end in MOCK_MODE.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    # Import inside fixture so the MOCK_MODE autouse fixture takes effect first
    from orchestrator.app.main import app
    return TestClient(app)


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["mock_mode"] is True


def test_demo_run_executes_all_four_steps(client):
    r = client.post("/demo/run")
    assert r.status_code == 200
    body = r.json()
    assert "steps" in body
    assert len(body["steps"]) == 4

    # Step 1: NOMOS pricing submitted
    s1 = body["steps"][0]
    assert s1["agent"] == "NOMOS"
    assert s1["result"]["status"] == "submitted"
    assert s1["result"]["trace_hash"].startswith("0x")
    assert s1["result"]["arc_tx_hash"].startswith("0x")
    assert s1["result"]["ipfs_cid"].startswith("bafy")

    # Step 2: OrderFilled
    s2 = body["steps"][1]
    assert s2["event"] == "OrderFilled"
    assert s2["builder_fee_usdc"] > 0

    # Step 3: SPATHA hedge
    s3 = body["steps"][2]
    assert s3["agent"] == "SPATHA"
    assert s3["result"]["status"] == "submitted"

    # Step 4: AGROS treasury
    s4 = body["steps"][3]
    assert s4["agent"] == "AGROS"
    assert s4["result"]["status"] == "submitted"


def test_demo_state_reflects_activity(client):
    client.post("/demo/run")

    # Inventory should show the filled position
    r = client.get("/state/inventory")
    assert r.status_code == 200
    inv = r.json()["inventory"]
    assert len(inv) >= 1
    assert any(item["net_exposure"] != 0 for item in inv)

    # Fills should be recorded
    r = client.get("/state/fills")
    assert r.status_code == 200
    fills = r.json()["fills"]
    assert len(fills) >= 1
    assert r.json()["cumulative_builder_fees_usdc"] > 0

    # Treasury should show the USYC subscribe
    r = client.get("/state/treasury")
    assert r.status_code == 200
    actions = r.json()["actions"]
    assert any(a["action"] == "usyc_subscribe" for a in actions)

    # Decisions should be queryable
    r = client.get("/state/decisions")
    assert r.status_code == 200
    decisions = r.json()["decisions"]
    assert len(decisions) >= 3  # 3 agents posted decisions


def test_trace_verification_matches_onchain_hash(client):
    """The whole point: trace hash committed on Arc matches sha256 of IPFS body."""
    client.post("/demo/run")

    # Get one of the decisions
    decisions = client.get("/state/decisions").json()["decisions"]
    submitted = [d for d in decisions if d.get("trace_hash")]
    assert submitted, "no submitted decisions found"
    decision = submitted[0]
    decision_id = decision["decision_id"]

    # Hit the verify endpoint — fetches IPFS, recomputes hash, compares to on-chain
    r = client.get(f"/traces/{decision_id}/verify")
    assert r.status_code == 200
    v = r.json()
    assert v["matches"] is True, "on-chain hash != recomputed IPFS hash"
    assert v["on_chain_hash"] == v["recomputed_hash"]


def test_invalid_decision_rejected(client):
    """POST a malformed decision; expect Pydantic validation 422."""
    r = client.post("/decisions/pricing", json={"agent_role": "nomos"})  # missing required fields
    assert r.status_code == 422


def test_duplicate_nonce_rejected(client):
    """Replay protection: same nonce twice for the same agent returns 409."""
    from shared.canonical import trace_hash
    import time

    payload = {
        "decision_id": 9999,
        "agent_role": "nomos",
        "nonce": 555_555,
        "ts_ms": int(time.time() * 1000),
        "rationale_hash": trace_hash({"k": "v"}),
        "market_id": "0x" + "a" * 40,
        "market_question": "Test",
        "bid": 0.4,
        "ask": 0.5,
        "size": 50.0,
        "confidence": 0.6,
        "appetite_profile": "balanced",
    }
    r1 = client.post("/decisions/pricing", json=payload)
    assert r1.status_code == 200

    # Second POST with the same nonce
    payload["decision_id"] = 9998
    payload["ts_ms"] = int(time.time() * 1000)
    r2 = client.post("/decisions/pricing", json=payload)
    assert r2.status_code == 409

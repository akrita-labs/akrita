"""Orchestrator HTTP-surface tests that do not require external adapters.

The mock adapter layer has been removed. The full decision lifecycle
(risk gate → trace pin → on-chain commit → execute) can only be
exercised once the real adapters land (see
docs/LIVE_IMPLEMENTATION_PLAN.md Phase 1). These tests cover the
surface that is independent of any external integration: liveness and
request-schema validation (both resolved before any adapter call).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from orchestrator.app.main import app
    return TestClient(app)


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # The mock_mode flag is gone — there is only the live path now.
    assert "mock_mode" not in body


def test_invalid_decision_rejected(client):
    """POST a malformed decision; Pydantic validation returns 422 before
    the handler (and any adapter) is reached."""
    r = client.post("/decisions/pricing", json={"agent_role": "nomos"})
    assert r.status_code == 422

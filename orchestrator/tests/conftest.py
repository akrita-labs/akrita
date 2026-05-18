"""pytest fixtures for AKRITA orchestrator tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make sure the repo root is on PYTHONPATH so imports work regardless of cwd
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _force_mock_mode(monkeypatch):
    """Every test runs in MOCK_MODE regardless of env."""
    monkeypatch.setenv("MOCK_MODE", "1")
    from adapters import reset_for_tests
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.fixture
def adapters():
    from adapters import get_adapters
    return get_adapters()

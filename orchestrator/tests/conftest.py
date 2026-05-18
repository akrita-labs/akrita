"""pytest fixtures for AKRITA orchestrator tests."""
from __future__ import annotations

import sys
from pathlib import Path

# Make sure the repo root is on PYTHONPATH so imports work regardless of cwd
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

---
name: akrita-nomos-sim
description: >
  Run the NOMOS pricing degeneration simulator for AKRITA. Use when the user says
  "run the nomos sim", "check pricing degeneration", "does the Conservative King
  template still trade", "stress test NOMOS quoting", or after changing NOMOS quote
  logic in agents/nomos/pricing.py. Read-only: runs a synthetic offline sweep, no
  network, no signing, no DB writes.
allowed-tools: Bash(.venv/bin/python:*), Read
---

# NOMOS pricing degeneration sim

Validates that each onboarding template still produces a fillable two-sided quote
across a synthetic grid of (mid, max_spread, inventory_ratio). The reviewer's
concern is that **Conservative King (offset 0.75) + a wide band may degenerate to
"does not trade"** — this sim is the gate that catches it.

## Run
```bash
cd /home/ubuntu/akrita && .venv/bin/python agents/nomos/sim.py
```
Output is one line per template:
```
[OK] balanced_counsel: 36/36 samples produced a fillable two-sided quote (offset 0.5)
[OK] aggressive_sovereign: ...
[OK|DEGENERATE] conservative_king: ...
```

Optionally run the pytest that asserts the safe templates don't degenerate:
```bash
cd /home/ubuntu/akrita && .venv/bin/python -m pytest orchestrator/tests/test_nomos_sim.py -q
```

## Interpret
- All `[OK]` → templates are healthy; nothing to do.
- `[DEGENERATE] conservative_king` → recommend tuning its NOMOS offset **0.75 → 0.65**
  in `shared/params.py` (`TEMPLATES["conservative_king"]`) **and** the matching seed
  in `migrations/versions/0003_platform_tables.py`. Do NOT change other templates.
  Re-run the sim after the change to confirm.

## Notes
- Pure compute. Safe to run anytime. The simulator reads templates from
  `shared.params.TEMPLATES` and the pricing math from `agents/nomos/pricing.py`.
- This skill only *reports*; it never edits params. Tuning is a separate, reviewed edit.

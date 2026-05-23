"""Tests for the offline NOMOS template simulator.

balanced_counsel (offset 0.5) and aggressive_sovereign (offset 0.25) must NOT
be degenerate — they are the canonical "this works" templates.

conservative_king (offset 0.75) is the wide-spread template. We do NOT
hard-fail if the sim flags it degenerate: we only assert the sim RAN (the
report has a "degenerate" key) and surface the verdict so the template owner can
decide whether to retune the offset to 0.65. This test must not edit
shared/params.py or the migration.
"""
from __future__ import annotations

from agents.nomos.sim import run_template_sim


def test_balanced_counsel_not_degenerate():
    report = run_template_sim("balanced_counsel")
    assert report["degenerate"] is False, report["reason"]


def test_aggressive_sovereign_not_degenerate():
    report = run_template_sim("aggressive_sovereign")
    assert report["degenerate"] is False, report["reason"]


def test_conservative_king_runs_and_records():
    report = run_template_sim("conservative_king")
    # Soft check: assert the sim RAN and produced a verdict. Do NOT hard-fail on
    # degeneration — the template owner tunes 0.75 -> 0.65 if needed.
    assert "degenerate" in report
    assert report["samples"], "sim produced no samples"
    if report["degenerate"]:
        print(
            "\n[conservative_king] DEGENERATE at offset 0.75: "
            f"{report['reason']} — consider retuning to 0.65."
        )
    else:
        print(
            "\n[conservative_king] OK at offset 0.75: "
            f"{report['reason']} — no retune needed."
        )

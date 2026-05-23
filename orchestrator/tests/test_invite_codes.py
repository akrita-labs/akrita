"""Pure tests for the per-template invite-code system (no network/DB).

Asserts the forced 4/4/4 cohort split, deterministic template encode/decode,
code uniqueness, single-use redemption, and graceful handling of garbage.
"""
from __future__ import annotations

import pytest

from scripts.bootstrap.invite_codes import (
    TEMPLATE_PREFIXES,
    distribution,
    generate_codes,
    redeem,
    template_for_code,
)

TEMPLATES = ["conservative_king", "balanced_counsel", "aggressive_sovereign"]


def _flatten(codes: dict[str, list[str]]) -> list[str]:
    return [c for code_list in codes.values() for c in code_list]


def test_generate_default_is_four_four_four():
    codes = generate_codes()
    assert set(codes) == set(TEMPLATES)
    assert sum(len(v) for v in codes.values()) == 12
    for template in TEMPLATES:
        assert len(codes[template]) == 4


def test_generate_respects_per_template():
    codes = generate_codes(per_template=2)
    assert sum(len(v) for v in codes.values()) == 6
    for template in TEMPLATES:
        assert len(codes[template]) == 2


def test_every_code_decodes_to_its_template():
    codes = generate_codes()
    for template, code_list in codes.items():
        for code in code_list:
            assert template_for_code(code) == template


def test_codes_are_unique():
    flat = _flatten(generate_codes())
    assert len(flat) == len(set(flat))


def test_codes_carry_template_prefix():
    codes = generate_codes()
    for template, code_list in codes.items():
        prefix = TEMPLATE_PREFIXES[template]
        for code in code_list:
            assert code.startswith(f"AKRITA-{prefix}-")


def test_template_for_code_handles_garbage():
    for garbage in [
        "",
        "nonsense",
        "AKRITA-UNKNOWN-01-7F3A",   # unknown prefix
        "OTHER-KING-01-7F3A",       # wrong namespace
        "AKRITA-KING-XX-7F3A",      # non-numeric index
        "AKRITA-KING-01",           # too few segments
        "AKRITA-KING-01-7F3A-EXTRA",  # too many segments
        None,
        12345,
    ]:
        assert template_for_code(garbage) is None


def test_template_for_code_is_case_insensitive():
    code = generate_codes(per_template=1)["conservative_king"][0]
    assert template_for_code(code.lower()) == "conservative_king"


def test_redeem_is_single_use_and_updates_distribution():
    codes = generate_codes()
    registry: dict[str, dict] = {}
    for template, code_list in codes.items():
        for code in code_list:
            registry[code] = {"template": template, "redeemed_by": None, "redeemed_at": None}

    code = codes["balanced_counsel"][0]

    # First redemption returns the template and marks the code used.
    assert redeem(registry, code, "user-1") == "balanced_counsel"
    assert registry[code]["redeemed_by"] == "user-1"
    assert registry[code]["redeemed_at"] is not None

    # Second redemption of the same code fails (single-use).
    with pytest.raises(ValueError):
        redeem(registry, code, "user-2")
    # Original redeemer preserved.
    assert registry[code]["redeemed_by"] == "user-1"

    dist = distribution(registry)
    assert dist["balanced_counsel"]["total"] == 4
    assert dist["balanced_counsel"]["redeemed"] == 1
    assert dist["balanced_counsel"]["available"] == 3
    assert dist["conservative_king"]["redeemed"] == 0


def test_redeem_unknown_code_raises():
    with pytest.raises(ValueError):
        redeem({}, "AKRITA-KING-99-DEAD", "user-1")

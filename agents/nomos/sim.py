"""
NOMOS — offline template simulator.

Sweeps `pricing.compute_quote` across a small synthetic grid for a given
onboarding template and reports whether the template can produce a two-sided
fillable quote. No network, no IO — pure functions over `shared.params`.

A template is "degenerate" when, across *every* sampled (mid, max_spread,
inventory_ratio), it fails to produce a two-sided fillable quote: i.e. the
clamped bid >= ask, or both legs are pinned at the same price boundary. In
practice this happens when the spread offset is so wide that bid/ask blow past
the [0.02, 0.98] clamp and collapse onto a single bound.

Run directly to print a report for all three templates:

    python agents/nomos/sim.py
"""
from __future__ import annotations

from agents.nomos.pricing import PRICE_CEIL, PRICE_FLOOR, compute_quote
from shared.params import TEMPLATES, validate_params

# Synthetic sweep grid. Mids span low/center/high probability; max_spreads span
# tight to very wide; inventory ratios span empty/balanced/full so the
# reservation-price tilt is exercised in both directions.
_MIDS = [0.20, 0.50, 0.80]
_MAX_SPREADS = [0.02, 0.05, 0.10, 0.20]
_INVENTORY_RATIOS = [0.0, 0.5, 1.0]


def _is_fillable(quote: dict) -> bool:
    """A quote is fillable when bid < ask and the two legs are not both pinned
    to the same price bound."""
    bid, ask = quote["bid"], quote["ask"]
    if bid >= ask:
        return False
    pinned_low = bid <= PRICE_FLOOR and ask <= PRICE_FLOOR
    pinned_high = bid >= PRICE_CEIL and ask >= PRICE_CEIL
    if pinned_low or pinned_high:
        return False
    return True


def run_template_sim(template_key: str) -> dict:
    """Run the synthetic sweep for one template's NOMOS params.

    Returns {"degenerate": bool, "samples": [...], "reason": str}. Each sample
    records the input grid point, the resulting quote, and whether it was
    fillable.
    """
    template = TEMPLATES[template_key]
    params = validate_params("nomos", template["nomos"])

    samples: list[dict] = []
    any_fillable = False
    for mid in _MIDS:
        for max_spread in _MAX_SPREADS:
            for inv in _INVENTORY_RATIOS:
                quote = compute_quote(mid, max_spread, inv, params)
                fillable = _is_fillable(quote)
                any_fillable = any_fillable or fillable
                samples.append(
                    {
                        "mid": mid,
                        "max_spread": max_spread,
                        "inventory_ratio": inv,
                        "quote": quote,
                        "fillable": fillable,
                    }
                )

    degenerate = not any_fillable
    fillable_count = sum(1 for s in samples if s["fillable"])
    if degenerate:
        reason = (
            f"No fillable two-sided quote across {len(samples)} samples — "
            f"offset {params.quote_spread_bps_offset_to_max_spread} collapses "
            "bid/ask onto a single clamp bound at every grid point."
        )
    else:
        reason = (
            f"{fillable_count}/{len(samples)} samples produced a fillable "
            f"two-sided quote (offset {params.quote_spread_bps_offset_to_max_spread})."
        )

    return {"degenerate": degenerate, "samples": samples, "reason": reason}


def _print_report(template_key: str) -> None:
    report = run_template_sim(template_key)
    status = "DEGENERATE" if report["degenerate"] else "OK"
    print(f"[{status}] {template_key}: {report['reason']}")


if __name__ == "__main__":
    for key in TEMPLATES:
        _print_report(key)

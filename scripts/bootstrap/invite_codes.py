#!/usr/bin/env python3
"""Per-template invite codes that enforce the forced 4/4/4 cohort split.

The AKRITA v1 spec wants the 12 recruited operators distributed evenly across
the three onboarding templates (conservative_king / balanced_counsel /
aggressive_sovereign). Rather than forcing a template choice in the UI, the
split is baked into the *invite codes* handed out at recruitment time: each
code deterministically encodes the template it grants, so redeeming a code
maps it straight to a template.

A code looks like:

    AKRITA-KING-01-7F3A

  - "AKRITA"  : fixed namespace prefix.
  - "KING"    : the TEMPLATE PREFIX — a short, human-pronounceable tag that
                deterministically identifies one of the three templates. The
                template is decoded purely from this segment (prefix lookup),
                so a redeemer never has to be told the template separately.
  - "01"      : the 1-based index of the code within its template batch.
  - "7F3A"    : a short random suffix (uppercase hex from `secrets`) that makes
                the code unique and unguessable.

Pure functions (generate_codes / template_for_code / write_registry /
load_registry / redeem) are import-safe; the argparse CLI is guarded by
__main__. Stdlib only (argparse, json, secrets, hashlib).

Usage:
    python scripts/bootstrap/invite_codes.py --generate [--per-template 4] \
        [--out invite_codes.json]
    python scripts/bootstrap/invite_codes.py --show --registry invite_codes.json
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from typing import Optional

# Fixed namespace so codes are visibly AKRITA invites.
NAMESPACE = "AKRITA"

# The three onboarding templates -> their short, human-pronounceable prefix.
# The prefix deterministically encodes the template (decode = reverse lookup).
TEMPLATE_PREFIXES: dict[str, str] = {
    "conservative_king": "KING",
    "balanced_counsel": "COUNSEL",
    "aggressive_sovereign": "SOVEREIGN",
}

# Reverse map for O(1) decode. Prefixes are unique by construction.
_PREFIX_TO_TEMPLATE: dict[str, str] = {v: k for k, v in TEMPLATE_PREFIXES.items()}

# Length (hex chars) of the random uniqueness suffix on each code.
_SUFFIX_HEX_LEN = 4


def _random_suffix() -> str:
    """Short, unguessable uppercase-hex suffix from a CSPRNG."""
    # secrets.token_hex(n) yields 2n hex chars; take the first _SUFFIX_HEX_LEN.
    return secrets.token_hex(_SUFFIX_HEX_LEN).upper()[:_SUFFIX_HEX_LEN]


def generate_codes(per_template: int = 4) -> dict[str, list[str]]:
    """Produce `per_template` unique invite codes for each of the 3 templates.

    Returns {template_key: [code, ...]}. Default per_template=4 -> 12 codes
    total (the forced 4/4/4 cohort distribution). Each code deterministically
    encodes its template via the prefix segment, so `template_for_code` can
    map any generated code back to its template.
    """
    if per_template < 0:
        raise ValueError("per_template must be >= 0")

    out: dict[str, list[str]] = {}
    seen: set[str] = set()
    for template, prefix in TEMPLATE_PREFIXES.items():
        codes: list[str] = []
        for n in range(1, per_template + 1):
            # Loop guards against the (vanishingly rare) random-suffix collision.
            while True:
                code = f"{NAMESPACE}-{prefix}-{n:02d}-{_random_suffix()}"
                if code not in seen:
                    break
            seen.add(code)
            codes.append(code)
        out[template] = codes
    return out


def template_for_code(code: str) -> Optional[str]:
    """Decode the template key from a code via its prefix segment.

    Returns None for anything that isn't a well-formed AKRITA invite code or
    whose prefix doesn't match a known template.
    """
    if not isinstance(code, str):
        return None
    parts = code.strip().upper().split("-")
    # Expected shape: NAMESPACE - PREFIX - INDEX - SUFFIX
    if len(parts) != 4:
        return None
    namespace, prefix, index, suffix = parts
    if namespace != NAMESPACE:
        return None
    if not (index.isdigit() and suffix):
        return None
    return _PREFIX_TO_TEMPLATE.get(prefix)


def write_registry(codes: dict[str, list[str]], path: str) -> dict[str, dict]:
    """Flatten {template: [codes]} into a redemption registry and persist it.

    Registry shape: {code: {template, redeemed_by, redeemed_at}}. Returns the
    in-memory registry that was written.
    """
    registry: dict[str, dict] = {}
    for template, code_list in codes.items():
        for code in code_list:
            registry[code] = {
                "template": template,
                "redeemed_by": None,
                "redeemed_at": None,
            }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, sort_keys=True)
        f.write("\n")
    return registry


def load_registry(path: str) -> dict[str, dict]:
    """Load a registry written by `write_registry`."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def redeem(registry: dict[str, dict], code: str, user_id: str) -> str:
    """Redeem a code for a user, enforcing single-use.

    Mutates `registry` in place (sets redeemed_by/redeemed_at) and returns the
    granted template key. Raises ValueError for unknown codes or codes that
    have already been redeemed.
    """
    entry = registry.get(code)
    if entry is None:
        raise ValueError(f"unknown invite code: {code}")
    if entry.get("redeemed_by") is not None:
        raise ValueError(
            f"invite code already redeemed by {entry['redeemed_by']}: {code}"
        )
    entry["redeemed_by"] = user_id
    entry["redeemed_at"] = int(time.time() * 1000)
    return entry["template"]


def distribution(registry: dict[str, dict]) -> dict[str, dict[str, int]]:
    """Cohort distribution counts per template: total / redeemed / available."""
    out: dict[str, dict[str, int]] = {
        t: {"total": 0, "redeemed": 0, "available": 0} for t in TEMPLATE_PREFIXES
    }
    for entry in registry.values():
        t = entry.get("template")
        if t not in out:
            out[t] = {"total": 0, "redeemed": 0, "available": 0}
        out[t]["total"] += 1
        if entry.get("redeemed_by") is not None:
            out[t]["redeemed"] += 1
        else:
            out[t]["available"] += 1
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_generate(per_template: int, out: Optional[str]) -> int:
    codes = generate_codes(per_template)
    total = sum(len(v) for v in codes.values())
    print(f"Generated {total} invite codes ({per_template} per template):\n")
    for template, code_list in codes.items():
        prefix = TEMPLATE_PREFIXES[template]
        print(f"  {template}  [{prefix}]")
        for code in code_list:
            print(f"      {code}")
        print()
    if out:
        write_registry(codes, out)
        print(f"Registry written to {out}")
    return 0


def _cmd_show(registry_path: str) -> int:
    registry = load_registry(registry_path)
    print(f"Invite registry: {registry_path}  ({len(registry)} codes)\n")
    for code in sorted(registry):
        entry = registry[code]
        if entry.get("redeemed_by") is not None:
            status = f"redeemed by {entry['redeemed_by']} @ {entry.get('redeemed_at')}"
        else:
            status = "available"
        print(f"  {code:28s} {entry.get('template'):22s} {status}")
    print("\nCohort distribution:")
    for template, counts in distribution(registry).items():
        print(
            f"  {template:22s} total={counts['total']} "
            f"redeemed={counts['redeemed']} available={counts['available']}"
        )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AKRITA per-template invite codes (4/4/4 cohort)")
    ap.add_argument("--generate", action="store_true", help="generate invite codes")
    ap.add_argument("--per-template", type=int, default=4, help="codes per template (default 4)")
    ap.add_argument("--out", default=None, help="write registry JSON to this path (with --generate)")
    ap.add_argument("--show", action="store_true", help="print redemption status + distribution")
    ap.add_argument("--registry", default="invite_codes.json", help="registry path (with --show)")
    args = ap.parse_args(argv)

    if args.generate:
        return _cmd_generate(args.per_template, args.out)
    if args.show:
        return _cmd_show(args.registry)

    ap.error("specify --generate or --show")
    return 2  # unreachable; argparse.error exits


if __name__ == "__main__":
    sys.exit(main())

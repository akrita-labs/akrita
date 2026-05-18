"""Canonical JSON / sha256 stability tests.

If these fail, trace integrity is broken: the hash committed on-chain
won't match the hash recomputed from the IPFS body, and verifyTrace
will always return false.
"""
from __future__ import annotations

import hashlib

from shared.canonical import canonical_json, sha256_hex, trace_hash


def test_canonical_json_is_deterministic_across_key_order():
    a = {"alpha": 1, "beta": 2, "gamma": 3}
    b = {"gamma": 3, "alpha": 1, "beta": 2}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_json_handles_nested_dicts():
    a = {"outer": {"z": 1, "a": 2}, "list": [{"k2": 2, "k1": 1}]}
    b = {"list": [{"k1": 1, "k2": 2}], "outer": {"a": 2, "z": 1}}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_json_has_no_whitespace():
    out = canonical_json({"key": "value", "num": 1})
    # Should be {"key":"value","num":1} exactly
    assert b" " not in out
    assert b"\n" not in out


def test_canonical_json_utf8_passthrough():
    # Unicode strings should pass through without escaping
    out = canonical_json({"key": "héllo αβγ"})
    assert "héllo αβγ".encode("utf-8") in out


def test_sha256_hex_format():
    h = sha256_hex(b"test data")
    assert h.startswith("0x")
    assert len(h) == 66  # 0x + 64 hex chars
    assert all(c in "0123456789abcdef" for c in h[2:])


def test_sha256_hex_matches_stdlib():
    data = b"AKRITA reasoning trace body"
    expected = "0x" + hashlib.sha256(data).hexdigest()
    assert sha256_hex(data) == expected


def test_trace_hash_recomputable_from_canonical_bytes():
    """The hash committed on-chain must equal sha256 of the IPFS-pinned body."""
    body = {
        "decision_id": 42,
        "agent_role": "nomos",
        "fundamentals": {"x": 1, "y": 2},
        "conclusion": {"bid": 0.5, "ask": 0.6},
    }
    on_chain_hash = trace_hash(body)
    # Simulate IPFS roundtrip: canonical bytes -> stored -> retrieved
    pinned_bytes = canonical_json(body)
    recomputed = sha256_hex(pinned_bytes)
    assert on_chain_hash == recomputed


def test_trace_hash_changes_with_any_content_change():
    body = {"k": "v", "n": 1}
    h1 = trace_hash(body)
    body["n"] = 2
    h2 = trace_hash(body)
    assert h1 != h2

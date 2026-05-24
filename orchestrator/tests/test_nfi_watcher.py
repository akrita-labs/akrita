"""Unit tests for the NFI blacklist watcher + rug-claim trace builder (pure)."""
from agents.nomos.claim_trace import build_claim_trace, claim_trace_hash
from agents.nomos.nfi_watcher import (
    build_claim_record,
    diff_additions,
    parse_blacklist,
    token_id,
)


def test_parse_blacklist_nested_and_bare():
    nested = {"hyperliquid": {"pair_blacklist": ["PEPE/USDC", "DOGE/USDC"]}}
    assert parse_blacklist(nested, "hyperliquid") == {"PEPE/USDC", "DOGE/USDC"}
    bare = {"pair_blacklist": ["X/USDT"]}
    assert parse_blacklist(bare, "binance") == {"X/USDT"}
    assert parse_blacklist({}, "binance") == set()


def test_diff_additions_only_new():
    old = {"A/USDT", "B/USDT"}
    new = {"A/USDT", "B/USDT", "C/USDT", "D/USDT"}
    assert diff_additions(old, new) == ["C/USDT", "D/USDT"]  # sorted, additions only
    assert diff_additions(new, old) == []  # removals are not additions


def test_token_id_case_insensitive_and_shape():
    a = token_id("PEPE/USDC", "hyperliquid")
    b = token_id("pepe/usdc", "Hyperliquid")
    assert a == b
    assert a.startswith("0x") and len(a) == 66


def test_claim_record_fields():
    r = build_claim_record("PEPE/USDC", "hyperliquid", "abc123def456")
    assert r["token"] == "PEPE"
    assert r["exchange"] == "hyperliquid"
    assert r["pair"] == "PEPE/USDC"
    assert r["source_file"] == "configs/blacklist-hyperliquid.json"
    assert r["token_id"].startswith("0x")
    assert r["drop_threshold_bps"] == 5000


def test_claim_trace_hash_is_deterministic():
    r = build_claim_record("PEPE/USDC", "hyperliquid", "abc123def456")
    b1 = build_claim_trace(r, credibility=0.8, decision_id=1)
    b2 = build_claim_trace(r, credibility=0.8, decision_id=1)
    h = claim_trace_hash(b1)
    assert h == claim_trace_hash(b2)  # same input -> same hash
    assert h.startswith("0x") and len(h) == 66


def test_claim_trace_hash_changes_with_input():
    r = build_claim_record("PEPE/USDC", "hyperliquid", "abc123def456")
    base = claim_trace_hash(build_claim_trace(r, credibility=0.8, decision_id=1))
    other = claim_trace_hash(build_claim_trace(r, credibility=0.9, decision_id=1))
    assert base != other

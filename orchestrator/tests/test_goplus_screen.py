"""Unit tests for the GoPlus rug-risk screener + claim trace (pure)."""
from agents.nomos.claim_trace import build_claim_trace, claim_trace_hash
from agents.nomos.goplus_screen import (
    build_claim_record,
    evaluate_risk,
    provenance_hash,
    token_id,
)

CLEAN = {"token_symbol": "USDC", "token_name": "USD Coin", "is_honeypot": "0", "buy_tax": "0", "sell_tax": "0", "is_proxy": "1"}
HONEYPOT = {"token_symbol": "SCAM", "token_name": "Scam", "is_honeypot": "1", "is_mintable": "1", "buy_tax": "0", "sell_tax": "0.15", "owner_address": "0xabc"}


def test_evaluate_clean_not_flagged():
    r = evaluate_risk(CLEAN)
    assert r["flagged"] is False
    assert r["reasons"] == []


def test_evaluate_flags_honeypot_mint_and_tax():
    r = evaluate_risk(HONEYPOT)
    assert r["flagged"] is True
    assert "honeypot" in r["reasons"]
    assert "owner can mint" in r["reasons"]
    assert any("sell tax" in x for x in r["reasons"])  # 15% >= 10% threshold
    assert r["severity"] == len(r["reasons"])


def test_tax_below_threshold_not_flagged():
    rec = {"buy_tax": "0.05", "sell_tax": "0.05", "is_honeypot": "0"}
    assert evaluate_risk(rec)["flagged"] is False


def test_token_id_case_insensitive_shape():
    a = token_id("0xAbC", 1)
    b = token_id("0xabc", 1)
    assert a == b and a.startswith("0x") and len(a) == 66


def test_provenance_hash_deterministic_and_sensitive():
    h1 = provenance_hash(CLEAN)
    assert h1 == provenance_hash(dict(CLEAN))  # order-independent (canonical)
    assert h1.startswith("0x") and len(h1) == 66
    assert h1 != provenance_hash(HONEYPOT)


def test_claim_record_and_trace_hash_deterministic():
    risk = evaluate_risk(HONEYPOT)
    rec = build_claim_record("0xdeadbeef", 1, HONEYPOT, risk)
    assert rec["token"] == "SCAM"
    assert rec["chain_id"] == 1
    assert rec["provenance"].startswith("0x")
    assert "honeypot" in rec["reasons"]
    h = claim_trace_hash(build_claim_trace(rec, decision_id=1))
    assert h == claim_trace_hash(build_claim_trace(rec, decision_id=1))
    assert h.startswith("0x") and len(h) == 66

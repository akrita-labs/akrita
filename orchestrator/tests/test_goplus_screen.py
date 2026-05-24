"""Unit tests for the GoPlus rug-risk screener + claim trace (pure)."""
from agents.nomos.claim_trace import build_claim_trace, claim_trace_hash
from agents.nomos.goplus_screen import (
    build_claim_record,
    evaluate_risk,
    provenance_hash,
    token_id,
)

CLEAN = {"token_symbol": "USDC", "token_name": "USD Coin", "is_honeypot": "0", "buy_tax": "0", "sell_tax": "0", "is_proxy": "1"}
# A legit token with ordinary admin functions (like USDT/PEPE) — must NOT flag.
LEGIT_ADMIN = {"token_symbol": "USDT", "is_honeypot": "0", "is_blacklisted": "1", "transfer_pausable": "1", "is_mintable": "1", "buy_tax": "0", "sell_tax": "0"}
# A real scam: honeypot, plus an admin function as context, plus a small tax.
HONEYPOT = {"token_symbol": "SCAM", "token_name": "Scam", "is_honeypot": "1", "is_mintable": "1", "buy_tax": "0", "sell_tax": "0.15", "owner_address": "0xabc"}


def test_evaluate_clean_not_flagged():
    r = evaluate_risk(CLEAN)
    assert r["flagged"] is False
    assert r["reasons"] == []


def test_legit_admin_functions_not_flagged():
    """USDT-style: blacklist + pausable + mintable but no STRONG indicator -> not a rug."""
    r = evaluate_risk(LEGIT_ADMIN)
    assert r["flagged"] is False
    assert r["reasons"] == []
    assert "blacklist function" in r["context"]  # recorded, not a trigger
    assert "owner can mint" in r["context"]


def test_evaluate_flags_honeypot_only_on_strong():
    r = evaluate_risk(HONEYPOT)
    assert r["flagged"] is True
    assert "honeypot (cannot sell)" in r["reasons"]
    assert "owner can mint" in r["context"]  # context, not a reason
    assert all("sell tax" not in x for x in r["reasons"])  # 15% < 50% scam threshold


def test_scam_level_tax_flags():
    rec = {"is_honeypot": "0", "buy_tax": "0.05", "sell_tax": "0.90"}
    r = evaluate_risk(rec)
    assert r["flagged"] is True
    assert any("sell tax 90%" in x for x in r["reasons"])


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
    assert any("honeypot" in r for r in rec["reasons"])
    assert "owner can mint" in rec["context"]
    h = claim_trace_hash(build_claim_trace(rec, decision_id=1))
    assert h == claim_trace_hash(build_claim_trace(rec, decision_id=1))
    assert h.startswith("0x") and len(h) == 66

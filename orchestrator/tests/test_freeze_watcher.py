"""Unit tests for the on-chain stablecoin freeze watcher (pure parts)."""
from agents.nomos.freeze_watcher import (
    ISSUERS,
    build_freeze_record,
    build_freeze_trace,
    decode_frozen_address,
    freeze_decision_id,
    freeze_token_id,
    freeze_trace_hash,
)

USDT = next(i for i in ISSUERS if i["symbol"] == "USDT")
USDC = next(i for i in ISSUERS if i["symbol"] == "USDC")

# USDT: _user NOT indexed -> address in data. USDC: _account indexed -> topics[1].
USDT_LOG = {
    "topics": [USDT["topic0"]],
    "data": "0x" + "00" * 12 + "11" * 20,
    "transactionHash": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    "blockNumber": "0x17",
}
USDC_LOG = {
    "topics": [USDC["topic0"], "0x" + "00" * 12 + "22" * 20],
    "data": "0x",
    "transactionHash": "0xcafecafecafecafecafecafecafecafecafecafecafecafecafecafecafecafe",
    "blockNumber": "0x2a",
}


def test_decode_address_from_data_and_topic():
    assert decode_frozen_address(USDT_LOG) == "0x" + "11" * 20
    assert decode_frozen_address(USDC_LOG) == "0x" + "22" * 20


def test_token_id_deterministic_shape():
    a = freeze_token_id("0xABc", "USDT")
    b = freeze_token_id("0xabc", "usdt")
    assert a == b and a.startswith("0x") and len(a) == 66


def test_decision_id_deterministic_from_tx():
    d = freeze_decision_id(USDT_LOG["transactionHash"])
    assert d == freeze_decision_id(USDT_LOG["transactionHash"])
    assert isinstance(d, int) and d > 0


def test_build_record_fields():
    r = build_freeze_record(USDT_LOG, USDT)
    assert r["issuer"] == "USDT"
    assert r["frozen_address"] == "0x" + "11" * 20
    assert r["event"] == "AddedBlackList"
    assert r["block"] == 0x17
    assert r["token_id"].startswith("0x")
    assert r["freeze_tx"] == USDT_LOG["transactionHash"]


def test_freeze_trace_hash_deterministic():
    r = build_freeze_record(USDC_LOG, USDC)
    h = freeze_trace_hash(build_freeze_trace(r, decision_id=1))
    assert h == freeze_trace_hash(build_freeze_trace(r, decision_id=1))
    assert h.startswith("0x") and len(h) == 66

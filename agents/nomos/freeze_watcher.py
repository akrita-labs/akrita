"""
NOMOS — on-chain stablecoin freeze watcher: the primary, zero-coverage-gap signal.

Reads issuer blacklist events straight from Ethereum (USDT `AddedBlackList`,
USDC `Blacklisted`) via eth_getLogs. Each freeze is a real, independently
verifiable on-chain event: Tether/Circle flagging an address as illicit
(sanctions / hack / fraud). NOMOS attests each on Arc — the freeze tx hash is
the provenance, so anyone can re-read the chain and confirm it.

Pure decode / id / trace helpers are import-safe + deterministic; `fetch_freezes`
is the only network edge (a single eth_getLogs per issuer over a block window).
"""
from __future__ import annotations

from typing import Optional

import httpx
from eth_utils import keccak

from shared.canonical import trace_hash

# Stablecoin issuers whose on-chain blacklist we mirror. `_account` is indexed on
# USDC (-> topics[1]) but NOT on USDT's legacy contract (-> data).
ISSUERS = [
    {
        "symbol": "USDT",
        "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "event": "AddedBlackList(address)",
    },
    {
        "symbol": "USDC",
        "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "event": "Blacklisted(address)",
    },
]
for _i in ISSUERS:
    _i["topic0"] = "0x" + keccak(text=_i["event"]).hex()
    _i["label"] = _i["event"].split("(")[0]


def decode_frozen_address(log: dict) -> str:
    """Frozen address from a blacklist log — indexed (topics[1]) or in data."""
    topics = log.get("topics") or []
    src = topics[1] if len(topics) > 1 else (log.get("data") or "")
    return "0x" + src[-40:].lower()


def freeze_token_id(frozen_address: str, issuer_symbol: str) -> str:
    """Deterministic bytes32 claim id: keccak256("address@ISSUER")."""
    return "0x" + keccak(text=f"{frozen_address.lower()}@{issuer_symbol.upper()}").hex()


def freeze_decision_id(freeze_tx: str) -> int:
    """Deterministic decision id from the freeze tx — re-scans are idempotent
    (the trace commit dedups on (agent, decisionId), so the same freeze can't be
    anchored twice)."""
    return int(freeze_tx.replace("0x", "")[:16], 16)


def build_freeze_record(log: dict, issuer: dict) -> dict:
    """Structured freeze attestation from a blacklist log."""
    addr = decode_frozen_address(log)
    return {
        "frozen_address": addr,
        "issuer": issuer["symbol"],
        "issuer_address": issuer["address"],
        "event": issuer["label"],
        "freeze_tx": log.get("transactionHash", ""),
        "block": int(log.get("blockNumber", "0x0"), 16) if isinstance(log.get("blockNumber"), str) else int(log.get("blockNumber", 0)),
        "token_id": freeze_token_id(addr, issuer["symbol"]),
    }


def build_freeze_trace(record: dict, *, decision_id: int) -> dict:
    """Canonical reasoning-trace body for a freeze attestation (mirrors TraceBody)."""
    return {
        "schema_version": "akrita/trace/v1",
        "decision_id": decision_id,
        "agent_role": "nomos",
        "decision_type": "freeze_attestation",
        "fundamentals": {
            "source": {
                "provider": f"{record['issuer']} blacklist (Ethereum)",
                "issuer_address": record["issuer_address"],
                "freeze_tx": record["freeze_tx"],
                "block": record["block"],
            },
            "frozen_address": record["frozen_address"],
        },
        "technical": {
            "signal": "stablecoin_blacklist",
            "issuer": record["issuer"],
            "event": record["event"],
        },
        "conclusion": {
            "action": "attest_freeze",
            "token_id": record["token_id"],
            "statement": (
                f"{record['issuer']} froze {record['frozen_address']} at block "
                f"{record['block']} — flagged illicit (sanctions / hack / fraud)"
            ),
        },
    }


def freeze_trace_hash(body: dict) -> str:
    return trace_hash(body)


async def _rpc(client: httpx.AsyncClient, url: str, method: str, params: list):
    r = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    r.raise_for_status()
    return r.json()


async def fetch_freezes(
    rpc_url: str,
    *,
    lookback_blocks: int = 90000,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict]:
    """Pull recent freeze events for all issuers, newest first. Network edge;
    returns [] on RPC failure so a scan loop degrades gracefully."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=25.0, headers={"content-type": "application/json", "User-Agent": "akrita-nomos"})
    out: list[dict] = []
    try:
        latest = int((await _rpc(client, rpc_url, "eth_blockNumber", []))["result"], 16)
        frm = hex(max(0, latest - lookback_blocks))
        for issuer in ISSUERS:
            try:
                resp = await _rpc(
                    client,
                    rpc_url,
                    "eth_getLogs",
                    [{"address": issuer["address"], "topics": [issuer["topic0"]], "fromBlock": frm, "toBlock": "latest"}],
                )
                for log in resp.get("result") or []:
                    out.append(build_freeze_record(log, issuer))
            except (httpx.HTTPError, KeyError, ValueError):
                continue
    except (httpx.HTTPError, KeyError, ValueError):
        return []
    finally:
        if own:
            await client.aclose()
    out.sort(key=lambda r: r["block"], reverse=True)
    return out


ETHERSCAN_API = "https://api.etherscan.io/api"


async def fetch_freezes_etherscan(
    api_key: str,
    *,
    from_block: int = 0,
    to_block: str = "latest",
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict]:
    """Deeper historical backfill via Etherscan's logs API (no narrow RPC range
    cap). Used when an Etherscan key is configured; returns [] on failure. Same
    log shape as eth_getLogs, so build_freeze_record applies unchanged."""
    if not api_key:
        return []
    own = client is None
    client = client or httpx.AsyncClient(timeout=25.0, headers={"User-Agent": "akrita-nomos"})
    out: list[dict] = []
    try:
        for issuer in ISSUERS:
            try:
                r = await client.get(
                    ETHERSCAN_API,
                    params={
                        "module": "logs",
                        "action": "getLogs",
                        "address": issuer["address"],
                        "topic0": issuer["topic0"],
                        "fromBlock": from_block,
                        "toBlock": to_block,
                        "apikey": api_key,
                    },
                )
                d = r.json()
                if str(d.get("status")) == "1":
                    for log in d.get("result") or []:
                        out.append(build_freeze_record(log, issuer))
            except (httpx.HTTPError, ValueError):
                continue
    finally:
        if own:
            await client.aclose()
    out.sort(key=lambda r: r["block"], reverse=True)
    return out

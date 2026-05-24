"""
NOMOS — GoPlus token-security screener: rug-risk signal ingestion.

Pure rule evaluation + token-id / provenance helpers (import-safe, deterministic,
unit-testable) plus a thin async GoPlus fetch. The signal: GoPlus Token Security
flags (honeypot, owner-can-mint, blacklist function, transfer-pausable, hidden
owner, self-destruct, high buy/sell tax). When a token trips the rules, NOMOS
issues a signed rug-risk claim anchored on Arc, carrying the sha256 of the GoPlus
response as verifiable provenance — anyone can re-query GoPlus and reproduce it.
"""
from __future__ import annotations

from typing import Optional

import httpx
from eth_utils import keccak

from shared.canonical import canonical_json, sha256_hex

GOPLUS_BASE = "https://api.gopluslabs.io/api/v1/token_security"
DEFAULT_CHAIN_ID = 1  # Ethereum mainnet
DEFAULT_WINDOW_S = 7 * 24 * 60 * 60
DEFAULT_DROP_THRESHOLD_BPS = 5000

# GoPlus boolean flags (string "1"/"0") that constitute rug risk -> human label.
_BOOL_RISK = {
    "is_honeypot": "honeypot",
    "is_blacklisted": "blacklist function",
    "can_take_back_ownership": "ownership re-takeable",
    "transfer_pausable": "transfers pausable",
    "hidden_owner": "hidden owner",
    "selfdestruct": "self-destruct",
    "is_mintable": "owner can mint",
    "cannot_sell_all": "cannot sell all",
    "trading_cooldown": "trading cooldown",
}
TAX_THRESHOLD = 0.10  # buy/sell tax at or above this (10%) is flagged


def _truthy(v) -> bool:
    return str(v) == "1"


def _tax(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def evaluate_risk(rec: dict, *, tax_threshold: float = TAX_THRESHOLD) -> dict:
    """Pure: given a GoPlus per-token record, return flagged / reasons / severity."""
    reasons: list[str] = []
    for flag, label in _BOOL_RISK.items():
        if _truthy(rec.get(flag)):
            reasons.append(label)
    bt, st = _tax(rec.get("buy_tax")), _tax(rec.get("sell_tax"))
    if bt >= tax_threshold:
        reasons.append(f"buy tax {bt * 100:.0f}%")
    if st >= tax_threshold:
        reasons.append(f"sell tax {st * 100:.0f}%")
    return {"flagged": bool(reasons), "reasons": reasons, "severity": len(reasons)}


def token_id(address: str, chain_id: int) -> str:
    """Deterministic bytes32 id: keccak256("address@chain_id"), 0x-hex."""
    return "0x" + keccak(text=f"{address.lower()}@{int(chain_id)}").hex()


def provenance_hash(rec: dict) -> str:
    """0x sha256 of the canonical GoPlus record — re-derivable by re-querying GoPlus."""
    return sha256_hex(canonical_json(rec))


def build_claim_record(
    address: str,
    chain_id: int,
    rec: dict,
    risk: dict,
    *,
    window_s: int = DEFAULT_WINDOW_S,
    drop_threshold_bps: int = DEFAULT_DROP_THRESHOLD_BPS,
) -> dict:
    """Structured rug-risk claim derived from a flagged GoPlus record."""
    keep = list(_BOOL_RISK) + ["buy_tax", "sell_tax", "owner_address"]
    return {
        "token": rec.get("token_symbol") or address[:10],
        "token_name": rec.get("token_name", ""),
        "address": address.lower(),
        "chain_id": int(chain_id),
        "token_id": token_id(address, chain_id),
        "source_provider": "goplus",
        "provenance": provenance_hash(rec),
        "reasons": risk["reasons"],
        "severity": risk["severity"],
        "flags": {k: rec[k] for k in keep if k in rec},
        "window_s": window_s,
        "drop_threshold_bps": drop_threshold_bps,
    }


async def fetch_token_security(
    address: str,
    chain_id: int = DEFAULT_CHAIN_ID,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Fetch the GoPlus per-token security record (no API key needed). Returns {}
    on failure / unknown token so a screen loop can skip gracefully."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "akrita-nomos"})
    try:
        r = await client.get(f"{GOPLUS_BASE}/{int(chain_id)}", params={"contract_addresses": address})
        r.raise_for_status()
        res = (r.json().get("result") or {})
        return res.get(address.lower()) or next(iter(res.values()), {}) or {}
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
        return {}
    finally:
        if own:
            await client.aclose()

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

# STRONG rug/scam indicators — any one is sufficient to issue a claim. These are
# the flags that actually mean "you will likely lose your money", not just "this
# token has an admin function".
_STRONG = {
    "is_honeypot": "honeypot (cannot sell)",
    "cannot_sell_all": "cannot sell all",
    "honeypot_with_same_creator": "creator linked to honeypots",
    "selfdestruct": "self-destruct",
    "hidden_owner": "hidden owner",
}
# COMMON admin capabilities — present in many LEGITIMATE tokens (USDT, USDC, PEPE
# all have blacklist/mint/pause). Recorded as context, but NEVER a claim trigger
# on their own — flagging USDT as a "rug" would be dishonest.
_CONTEXT = {
    "is_blacklisted": "blacklist function",
    "transfer_pausable": "transfers pausable",
    "is_mintable": "owner can mint",
    "can_take_back_ownership": "ownership re-takeable",
    "trading_cooldown": "trading cooldown",
}
SCAM_TAX = 0.50  # buy/sell tax at or above 50% is scam-level (legit tokens are < ~15%)


def _truthy(v) -> bool:
    return str(v) == "1"


def _tax(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def evaluate_risk(rec: dict, *, scam_tax: float = SCAM_TAX) -> dict:
    """Pure: classify a GoPlus per-token record.

    `flagged` is True only on STRONG indicators or scam-level tax — so legit
    tokens with ordinary admin functions (USDT/PEPE) are NOT flagged. `context`
    records the benign-but-notable capabilities for the trace.
    """
    reasons: list[str] = []
    for flag, label in _STRONG.items():
        if _truthy(rec.get(flag)):
            reasons.append(label)
    bt, st = _tax(rec.get("buy_tax")), _tax(rec.get("sell_tax"))
    if bt >= scam_tax:
        reasons.append(f"buy tax {bt * 100:.0f}%")
    if st >= scam_tax:
        reasons.append(f"sell tax {st * 100:.0f}%")
    context = [label for flag, label in _CONTEXT.items() if _truthy(rec.get(flag))]
    return {
        "flagged": bool(reasons),
        "reasons": reasons,
        "context": context,
        "severity": len(reasons),
    }


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
    keep = list(_STRONG) + list(_CONTEXT) + ["buy_tax", "sell_tax", "owner_address"]
    return {
        "token": rec.get("token_symbol") or address[:10],
        "token_name": rec.get("token_name", ""),
        "address": address.lower(),
        "chain_id": int(chain_id),
        "token_id": token_id(address, chain_id),
        "source_provider": "goplus",
        "provenance": provenance_hash(rec),
        "reasons": risk["reasons"],
        "context": risk.get("context", []),
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

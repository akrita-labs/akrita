"""
NOMOS — NostalgiaForInfinity (NFI) blacklist watcher: rug-risk signal ingestion.

Pure parsing/diff core (import-safe, deterministic, unit-testable) plus a thin
async GitHub fetch. The signal: every token added to an NFI blacklist
(`configs/blacklist-<exchange>.json`) is a real commit/diff. Each *new* addition
becomes a structured rug-risk claim that NOMOS anchors as a reasoning trace and
registers on-chain (see agents/nomos/claim_trace.py + ClaimRegistry).

The pure functions touch no network/IO; `fetch_blacklist` is the only async edge.
"""
from __future__ import annotations

from typing import Optional

import httpx
from eth_utils import keccak

NFI_REPO = "iterativv/NostalgiaForInfinity"
_RAW = "https://raw.githubusercontent.com/{repo}/main/configs/blacklist-{exchange}.json"
_COMMITS = "https://api.github.com/repos/{repo}/commits?path=configs/blacklist-{exchange}.json&per_page=1"

# 7-day window, 50% drop — defaults; the orchestrator overrides from settings.
DEFAULT_WINDOW_S = 7 * 24 * 60 * 60
DEFAULT_DROP_THRESHOLD_BPS = 5000


def parse_blacklist(doc: dict, exchange: str) -> set[str]:
    """Extract the `pair_blacklist` set from a freqtrade blacklist config.

    Accepts both the nested `{"<exchange>": {"pair_blacklist": [...]}}` shape and
    a bare `{"pair_blacklist": [...]}`.
    """
    if not isinstance(doc, dict):
        return set()
    node = doc.get(exchange)
    if not isinstance(node, dict):
        node = doc
    pairs = node.get("pair_blacklist", []) if isinstance(node, dict) else []
    return {str(p).strip() for p in pairs if str(p).strip()}


def diff_additions(old: set[str], new: set[str]) -> list[str]:
    """Pairs present in `new` but not `old` (additions only), sorted for determinism."""
    return sorted(new - old)


def token_id(pair: str, exchange: str) -> str:
    """Deterministic bytes32 token id: keccak256("PAIR@exchange"), 0x-hex.

    Case-insensitive so "PEPE/USDC" @ "Hyperliquid" == "pepe/usdc" @ "hyperliquid".
    """
    return "0x" + keccak(text=f"{pair.upper()}@{exchange.lower()}").hex()


def build_claim_record(
    pair: str,
    exchange: str,
    source_commit: str,
    *,
    window_s: int = DEFAULT_WINDOW_S,
    drop_threshold_bps: int = DEFAULT_DROP_THRESHOLD_BPS,
) -> dict:
    """Structured rug-risk claim derived from one blacklist addition."""
    return {
        "token": pair.split("/")[0].upper(),
        "pair": pair.upper(),
        "exchange": exchange.lower(),
        "token_id": token_id(pair, exchange),
        "source_repo": NFI_REPO,
        "source_file": f"configs/blacklist-{exchange.lower()}.json",
        "source_commit": source_commit,
        "window_s": window_s,
        "drop_threshold_bps": drop_threshold_bps,
    }


async def fetch_blacklist(
    exchange: str,
    *,
    repo: str = NFI_REPO,
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[set[str], str]:
    """Fetch the current blacklist pairs + the latest commit sha for the file.

    Network edge; degrades to ("", "") shapes gracefully so a poll loop can
    skip on transient failures.
    """
    own = client is None
    client = client or httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "akrita-nomos"})
    try:
        raw = await client.get(_RAW.format(repo=repo, exchange=exchange.lower()))
        raw.raise_for_status()
        pairs = parse_blacklist(raw.json(), exchange)
        sha = ""
        try:
            commits = await client.get(_COMMITS.format(repo=repo, exchange=exchange.lower()))
            if commits.status_code == 200:
                data = commits.json()
                if isinstance(data, list) and data:
                    sha = str(data[0].get("sha", ""))
        except httpx.RequestError:
            pass
        return pairs, sha
    finally:
        if own:
            await client.aclose()

"""
Redis client + helpers.

Two things live in Redis:

  1. Monotonic counters — decision IDs per agent role.
  2. Nonce replay set — claimed nonces per agent role (durable, restart-safe).

We also expose a generic cache surface (get/set with TTL) that other
modules can use as needed.

Lifecycle: `init_redis()` at orchestrator startup, `shutdown_redis()` at
shutdown. Callers grab the global client via `get_redis()`.
"""
from __future__ import annotations

from redis.asyncio import Redis

from orchestrator.app.config import settings


_client: Redis | None = None


def init_redis(url: str | None = None) -> Redis:
    """Initialise the global Redis client. Idempotent."""
    global _client
    if _client is not None:
        return _client
    _client = Redis.from_url(
        url or settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    return _client


async def shutdown_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def get_redis() -> Redis:
    if _client is None:
        init_redis()
    assert _client is not None
    return _client


# ---------------------------------------------------------------------------
# Monotonic decision counters
# ---------------------------------------------------------------------------

def _counter_key(agent_role: str) -> str:
    return f"akrita:decision_counter:{agent_role}"


async def next_decision_id(agent_role: str) -> int:
    """Atomic per-agent decision ID counter."""
    r = get_redis()
    return int(await r.incr(_counter_key(agent_role)))


async def reset_decision_counter(agent_role: str, to: int = 0) -> None:
    """Test/admin helper — reset the counter."""
    r = get_redis()
    await r.set(_counter_key(agent_role), to)


# ---------------------------------------------------------------------------
# Nonce replay protection
# ---------------------------------------------------------------------------

def _nonce_key(agent_role: str) -> str:
    return f"akrita:nonces:{agent_role}"


async def claim_nonce(agent_role: str, nonce: int) -> bool:
    """SADD returns 1 if the nonce was newly added, 0 if it was already
    in the set. Returns True only when the nonce was unused.
    """
    r = get_redis()
    added = await r.sadd(_nonce_key(agent_role), int(nonce))
    return bool(added)


async def has_nonce(agent_role: str, nonce: int) -> bool:
    r = get_redis()
    return bool(await r.sismember(_nonce_key(agent_role), int(nonce)))


# ---------------------------------------------------------------------------
# Wallet nonce tracking (per-chain transaction nonce for signing)
# ---------------------------------------------------------------------------

def _wallet_nonce_key(wallet_id: str, chain: str) -> str:
    return f"akrita:wallet_nonce:{chain}:{wallet_id}"


async def get_wallet_nonce(wallet_id: str, chain: str) -> int | None:
    r = get_redis()
    v = await r.get(_wallet_nonce_key(wallet_id, chain))
    return int(v) if v is not None else None


async def set_wallet_nonce(wallet_id: str, chain: str, nonce: int) -> None:
    r = get_redis()
    await r.set(_wallet_nonce_key(wallet_id, chain), int(nonce))


async def reserve_next_wallet_nonce(wallet_id: str, chain: str) -> int:
    """Atomic increment-and-return for the wallet's next tx nonce.
    Assumes set_wallet_nonce was called once at startup with the
    on-chain nonce so the counter is anchored to reality.
    """
    r = get_redis()
    return int(await r.incr(_wallet_nonce_key(wallet_id, chain))) - 1


# ---------------------------------------------------------------------------
# Generic cache surface
# ---------------------------------------------------------------------------

async def cache_get(key: str) -> str | None:
    return await get_redis().get(key)


async def cache_set(key: str, value: str, ttl_sec: int | None = None) -> None:
    if ttl_sec:
        await get_redis().setex(key, ttl_sec, value)
    else:
        await get_redis().set(key, value)


async def cache_delete(key: str) -> None:
    await get_redis().delete(key)

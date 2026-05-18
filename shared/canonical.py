"""
Canonical JSON encoding + sha256 helpers.

Trace integrity depends on canonical byte-serialization: the same trace
body must always produce the same sha256 regardless of dict ordering,
whitespace, or float precision quirks. Without canonical encoding,
the on-chain commit hash won't match the IPFS body hash and the
TraceRegistry.verifyTrace() function will return false even for
unmodified content.

We use JCS (RFC 8785) semantics: sorted keys, no whitespace, UTF-8,
canonical number representation.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Serialize obj as canonical JSON bytes (RFC 8785 inspired).

    - Keys sorted lexicographically at every level
    - No whitespace
    - UTF-8 encoded
    - ensure_ascii=False so unicode strings pass through unchanged
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_default,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return 0x-prefixed lowercase hex sha256 digest."""
    return "0x" + hashlib.sha256(data).hexdigest()


def trace_hash(trace_body: Any) -> str:
    """Convenience: canonical JSON encode + sha256 hex.

    This is the value that gets committed to TraceRegistry.commitTrace().
    Anyone fetching the IPFS body later can rerun this function and
    confirm the on-chain hash matches.
    """
    return sha256_hex(canonical_json(trace_body))


def _default(o: Any) -> Any:
    """Fallback encoder for types json doesn't know natively."""
    # Pydantic v2 models
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    # Pydantic v1 models
    if hasattr(o, "dict"):
        return o.dict()
    # Decimal -> str (avoid float precision loss)
    if hasattr(o, "as_tuple"):
        return str(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

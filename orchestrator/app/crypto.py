"""
Symmetric encryption for per-user secrets at rest.

Per-user Polymarket API creds + signer-key material are stored encrypted
in `builder_profiles.*_enc` columns. We use Fernet (AES-128-CBC + HMAC)
with a single operator master key from `AKRITA_SECRET_KEY`.

The master key is a crown-jewel secret: if it leaks, every stored user
credential is exposed. Keep it out of the repo (env / secrets manager)
and rotate by re-encrypting on key change (out of scope for the prototype).
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from shared.config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.akrita_secret_key
    if not key:
        raise RuntimeError(
            "AKRITA_SECRET_KEY not set — cannot encrypt/decrypt user secrets. "
            'Generate one: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


def encrypt(plaintext: str | None) -> bytes | None:
    """Encrypt a string to Fernet token bytes. None passes through."""
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode())


def decrypt(token: bytes | None) -> str | None:
    """Decrypt Fernet token bytes back to a string. None passes through."""
    if token is None:
        return None
    return _fernet().decrypt(bytes(token)).decode()

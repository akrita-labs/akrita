"""
NanopaymentReal — IPFS pinning for trace bodies.

Phase-2 scope: pin canonical trace bytes to IPFS via Pinata and fetch
them back by CID. The x402/Gateway nanopayment settlement layer (paying
the pin provider per-trace through Circle) is Phase 7 — until then,
`pay()` is a documented no-op and pinning uses the Pinata JWT directly.

The CID returned here is real and publicly resolvable, which is all the
trace pipeline + on-chain verification need.
"""
from __future__ import annotations

import httpx

from shared.config import settings


PINATA_PIN_URL = "https://api.pinata.cloud/pinning/pinFileToIPFS"
PINATA_GATEWAY = "https://gateway.pinata.cloud/ipfs"
PUBLIC_GATEWAYS = [
    "https://gateway.pinata.cloud/ipfs",
    "https://ipfs.io/ipfs",
    "https://cloudflare-ipfs.com/ipfs",
]


class NanopaymentReal:
    def __init__(self) -> None:
        self._provider = settings.pin_provider
        self._pinata_jwt = settings.pinata_jwt
        self._web3_storage_token = settings.web3_storage_token
        if self._provider == "pinata" and not self._pinata_jwt:
            raise RuntimeError("PIN_PROVIDER=pinata but PINATA_JWT is empty")

    async def pin_to_ipfs(self, content_bytes: bytes, max_price_usdc: float = 0.005) -> str:
        """Pin bytes to IPFS; return the CID. `max_price_usdc` is reserved for
        the Phase-7 x402 settlement path and currently unused."""
        if self._provider == "pinata":
            return await self._pin_pinata(content_bytes)
        raise NotImplementedError(f"pin provider {self._provider!r} not implemented")

    async def _pin_pinata(self, content_bytes: bytes) -> str:
        files = {"file": ("trace.json", content_bytes, "application/json")}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                PINATA_PIN_URL,
                headers={"Authorization": f"Bearer {self._pinata_jwt}"},
                files=files,
            )
            resp.raise_for_status()
            return resp.json()["IpfsHash"]

    async def fetch_from_ipfs(self, cid: str) -> bytes | None:
        """Fetch pinned content by CID, trying gateways in order."""
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for gw in PUBLIC_GATEWAYS:
                try:
                    resp = await client.get(f"{gw}/{cid}")
                    if resp.status_code == 200:
                        return resp.content
                except httpx.RequestError:
                    continue
        return None

    async def pay(self, recipient: str, amount_usdc: float, memo: str = "") -> str:
        """Phase-7: x402/Gateway batched settlement. No-op until the
        TypeScript trace sidecar lands."""
        return "nanopayment-deferred-to-phase-7"

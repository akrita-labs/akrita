# Live integration guide

This document covers wiring real-world adapters, one primitive at a time. Every external surface is defined behind a `Protocol` interface in `adapters/base.py`; adding an integration is a matter of writing a class that implements the protocol and wiring it into `get_adapters()` in `adapters/__init__.py`.

The order below reflects critical-path lead times. Day 1 actions have multi-day external dependencies and must be filed before anything else.

---

## Day 1 — file the two long-lead admissions

### Polymarket V2 builder code

1. Sign in at <https://polymarket.com>.
2. Open **Settings → Builder** and request a builder profile.
3. Copy the resulting `bytes32` code (looks like `0x00…01`) into `.env` as `POLY_BUILDER_CODE`.
4. While waiting for mainnet admission, develop against Polymarket V2 testnet — the V2 SDK accepts builder codes identically, only the leaderboard surface differs.

### USYC Arc testnet allow-listing

1. Get testnet USDC from <https://faucet.circle.com> (select Arc testnet).
2. Open a Circle Support ticket and include your Arc testnet wallet address with the request "allow-list this address for testnet USYC subscriptions on Arc."
3. Approval typically lands in 24–48 hours.
4. Once approved, the wallet can call the testnet USYC Teller contract listed at <https://docs.arc.io/arc/references/contract-addresses>.

Both actions are external and asynchronous. Fire them on Day 1 so the rest of the build has a clear runway.

---

## Polymarket V2 (Days 4–7)

The Polymarket V2 adapter must cover the CLOB feed, fills, and builder-fee accrual. Implementing it requires:

1. `pip install py-clob-client-v2` (the legacy `py-clob-client` is V1 and will not work against the April 28 2026 CLOB).
2. Import `ClobClient` from `polymarket_clob_client_v2`.
3. The V2 EIP-712 domain version is `"2"`, not `"1"`. The `verifyingContract` moves to the new CTF Exchange V2 address.
4. The order struct dropped `nonce`, `feeRateBps`, and `taker`. It added `timestamp` (ms), `metadata` (bytes32), and `builder` (bytes32). The builder field is where the team's `POLY_BUILDER_CODE` lands.
5. Polymarket V2 uses **pUSD as collateral, not USDC**. After Gateway lands USDC on Polygon, the Treasury Agent must call the Collateral Onramp contract's `wrap()` function to convert USDC → pUSD. The reverse on redemption.
6. Builder fee accrual is per-fill in pUSD on the V2 contract; sweep back to Arc via Gateway weekly (or once an economic threshold is hit, default $5).

Reference shape for the real adapter:

```python
class PolymarketReal(PolymarketAdapter):
    def __init__(self, builder_code: str, signer: LocalAccount, chain_id: int = 137):
        self.client = ClobClient(
            host="https://clob.polymarket.com",
            chain=chain_id,
            signer=signer,
            signatureType=3,                  # POLY_PROXY for the SibylFi keeper
            funderAddress=signer.address,
        )
        self.builder_code = builder_code

    async def post_quote(self, decision: PricingDecision) -> str:
        response = await self.client.createAndPostOrder(
            {
                "tokenID": decision.market_id,
                "price": float(decision.bid),
                "size": float(decision.size),
                "side": "BUY",
                "builderCode": self.builder_code,
            },
            {"tickSize": "0.01", "negRisk": False},
            order_type="GTC",
        )
        return response.order_id
```

Validate end-to-end on testnet before mainnet cut-over: post a quote, watch the OrderFilled event, confirm `builder` matches `POLY_BUILDER_CODE` in event args.

---

## USYC testnet (Days 4–5)

After the allow-list ticket clears, the integration is straightforward. USYC accrues value via NAV-based price appreciation at the published ~3.93% APY.

Real implementation:

```python
class USYCArcTestnet(USYCAdapter):
    USYC_TELLER = "<address from docs.arc.io>"
    USYC_TOKEN  = "<address from docs.arc.io>"

    async def subscribe(self, usdc_amount: Decimal) -> SubscribeReceipt:
        # 1. Approve USDC spend by the Teller
        await self.wallet.approve(
            token=USDC_ARC, spender=self.USYC_TELLER, amount=usdc_amount
        )
        # 2. Call Teller.subscribe(usdc_amount, recipient=wallet.address)
        tx = await self.wallet.write(
            self.USYC_TELLER, "subscribe", [usdc_amount, self.wallet.address]
        )
        receipt = await tx.wait()
        return SubscribeReceipt(
            usdc_in=usdc_amount,
            usyc_out=Decimal(receipt.event("Subscribed").args.usycAmount),
            nav=Decimal(receipt.event("Subscribed").args.navAtSettlement),
            tx_hash=receipt.transactionHash.hex(),
        )

    async def redeem(self, usyc_amount: Decimal) -> RedeemReceipt: ...
```

The Teller exposes `subscribe`, `redeem`, and a NAV oracle. The 0.03% redemption fee is netted automatically — no manual accounting needed.

---

## Circle Gateway (Days 5–7)

Gateway is on mainnet across 11 chains as of May 2026 (Arbitrum, Avalanche, Base, Ethereum, Optimism, Polygon, Unichain, and more). Arc testnet support is documented at <https://developers.circle.com/gateway>.

The two-step flow:

1. Deposit USDC into the Gateway Wallet contract to populate the unified balance.
2. Submit a signed burn intent via the Gateway API; the API returns a signed attestation; submit the attestation to a Gateway Minter on the destination chain.

The pseudocode in `docs/ARCHITECTURE.md` matches the real shape — wrap it in an async adapter and you're done. Sub-500ms transfer is the documented SLA. If Gateway is unavailable, fall back to CCTP Fast Transfer (8–20s).

---

## Hyperliquid (Days 5–7)

Hyperliquid is the primary hedge venue. USDC margin only — no native USYC support yet — so the Hedge Agent's USYC-redeem-then-Gateway-transfer-then-open-position flow described in `docs/ARCHITECTURE.md` is the real path, not a fallback.

```python
pip install hyperliquid-python-sdk
```

The SDK exposes `Exchange.order()` for opening positions and `Info.user_state()` for fetching margin & PnL. Testnet endpoint: `https://api.hyperliquid-testnet.xyz`. Affiliate / referral codes attach via the API client config.

End-to-end test before mainnet: open a 1 USDC perp on BTC-PERP testnet, watch the position appear via Info, close it. The full open/close lifecycle should clear in under 3 seconds.

---

## Nanopayments + IPFS pinning (Day 6)

The Nanopayment adapter posts to a pinning provider (Pinata, web3.storage, Lighthouse) that accepts Circle Nanopayments via the x402 protocol and returns a content-addressed CID.

```python
from x402_client import Nanopay

nano = Nanopay(wallet_id=TRACE_WALLET_ID, facilitator=COINBASE_FACILITATOR)

async def pin(canonical_bytes: bytes) -> str:
    resp = await nano.post(
        url="https://api.pin-provider.io/pin",
        json={"content": base64.b64encode(canonical_bytes).decode()},
        max_price_usdc=Decimal("0.005"),
    )
    return resp.json()["cid"]
```

The facilitator handles the 402 challenge-response: the provider returns `HTTP 402 Payment Required` with a price quote; the client signs a Nanopayment authorization; the provider verifies and serves the request. Each pin costs $0.001–$0.005 USDC — at 500 decisions over 14 days, ~$0.50–$2.50 total.

---

## Arc TraceRegistry + BuilderRegistry (Days 3–4)

Deploy with Foundry against Arc testnet:

```bash
cd contracts
forge build
forge script script/Deploy.s.sol \
    --rpc-url $ARC_RPC_URL \
    --private-key $DEPLOYER_KEY \
    --broadcast
```

Copy the two contract addresses into `.env` as `TRACE_REGISTRY_ADDRESS` and `BUILDER_REGISTRY_ADDRESS`. The orchestrator picks them up at boot.

The `Deploy.s.sol` script in this repo deploys both contracts and registers the keeper agent with its builder code in a single broadcast. Re-run only on testnet redeploys.

---

## Integration checklist

The orchestrator's `get_adapters()` factory (`adapters/__init__.py`) is where each real adapter class is wired in. Before wiring an adapter into the factory, verify it individually with a corresponding script under `scripts/` (one script per adapter — write these as you go).

Suggested order of cut-over, lowest blast radius first:

1. USYC testnet (read-only NAV queries, then small subscribe/redeem)
2. Circle Wallets (provision the four keeper wallets, assert spend policies)
3. TraceRegistry / BuilderRegistry (deploy + register)
4. Nanopayment IPFS pinning (pin a single trace end-to-end)
5. Gateway (small cross-chain USDC test transfer)
6. Polymarket V2 testnet (post one quote, watch one fill, confirm builder attribution)
7. Hyperliquid testnet (open and close a 1 USDC perp position)
8. Polymarket V2 mainnet (Day 8+, after testnet has been clean for 48 hours)

Wire one adapter into `get_adapters()` at a time so a regression in one integration can be isolated rather than taking down the whole stack.

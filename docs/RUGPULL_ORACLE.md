# AKRITA Rugpull Oracle — design (Pivot 1 + Gateway)

> Pivot away from Polymarket V2 (no public testnet → execution can't be demoed)
> to a target that runs **end-to-end on testnet today**: a signed, on-chain
> **rug-risk oracle** sourced from the **GoPlus token-security** signal, with a
> two-sided USDC bond market and cross-chain bond funding via Circle Gateway.
> Reuses ~90% of AKRITA: the trace pipeline, Arc/USYC/Hyperliquid/Gateway adapters,
> BuilderRegistry/ERC-8004, the Risk Agent, and the frontend shell.

## The signal (verified)

**GoPlus Token Security API** (`api.gopluslabs.io/api/v1/token_security/<chain_id>`)
— free, no key, multi-EVM. Returns a structured per-token record with concrete
rug-risk flags: `is_honeypot`, `buy_tax`/`sell_tax`, `is_blacklisted`,
`is_mintable`, `can_take_back_ownership`, `transfer_pausable`, `hidden_owner`,
`selfdestruct`, `owner_address`. Verified live (USDC → `code:1`, clean flags).

NOMOS screens candidate tokens; one that trips the rug-risk rules (any boolean
flag set, or buy/sell tax ≥ 10%) becomes a claim. The GoPlus response is hashed
(sha256 of canonical JSON) into the claim as **provenance** — anyone can re-query
GoPlus and reproduce the flags + hash.

> Note: GoPlus attests rug *capability* (mintable, honeypot, drainable), not rug
> *timing*. So this is a verifiable **risk-attestation** oracle; bond resolution
> ("did it actually drop > threshold?") is a separate price-feed/manual step.
>
> Earlier attempt: the NostalgiaForInfinity blacklist was disproven as a signal —
> 6–8 regex categories per exchange, zero per-token events. GoPlus replaced it.

## Product

When NOMOS flags a token via GoPlus, AKRITA **issues a signed claim**:
"TOKEN flagged by GoPlus (honeypot, owner-can-mint, …) — rug risk." The claim is:
1. serialized to a canonical reasoning trace → sha256 → IPFS → **TraceRegistry on Arc**
   (the existing pipeline, unchanged), and
2. registered in a new **ClaimRegistry** with an optional two-sided **bond market**
   ("will TOKEN drop > threshold within the window?"). Stakers bond USDC for/against;
   on resolution the wrong side is slashed pro-rata to the winners.

The product *is* the trace: a verifiable, on-chain attestation with reproducible
GoPlus provenance.

## Agent remap

| Agent | Was | Now |
|---|---|---|
| **NOMOS** | quoting / market maker | **claim issuer** — screens tokens via GoPlus, builds the reasoning trace (flags + provenance), anchors it, calls `issueClaim`. |
| **SPATHA** | Polymarket inventory hedger | **exposure hedger** — same Hyperliquid adapter, hedges directional risk on issued claims. |
| **AGROS** | treasury | **bond treasury** — holds idle bond capital in USYC between events; bond pool on Arc is funded cross-chain via **Gateway**. |

## ClaimRegistry contract (Arc) — deployed `0x16aD24beEBa619f7b8C2fcFDa1F1ec1f6210F405`

Minimal, no-OpenZeppelin, matches TraceRegistry style. `owner` + `authorizedIssuers`
(NOMOS keeper) + `authorizedResolvers`. Per claim: `tokenId` (keccak of
`address@chain_id`), `sourceCommit` (GoPlus provenance sha256), `traceHash`
(→ TraceRegistry), `ipfsCid`, `window`, `dropThresholdBps`, `status`. Bond market:
`stake(claimId, backsClaim, amount)` (USDC `transferFrom`), `resolve(claimId, rugged)`
(resolver), `withdraw(claimId)` (winners get stake + pro-rata of the losing pool;
losers slashed; idempotent). Trace anchoring stays in `TraceRegistry`.

## Gateway bond flow (load-bearing Circle usage)

Bond capital originates as USDC on an EVM source testnet → **Gateway** (deposit → burn
intent → mint) → the Arc bond pool. AGROS parks idle bonds in USYC and routes inflows
via the existing `GatewayReal` adapter. Source chain is config-driven
(`bond_source_chain` / `bond_source_domain`); set it to whichever testnet is funded.

## Reuse map

- **Unchanged:** trace pipeline, `ArcReal`, `USYCReal` (allowlisted), `HyperliquidReal`
  (reads), `GatewayReal`, BuilderRegistry/ERC-8004, frontend shell, canonical hashing.
- **New:** `ClaimRegistry.sol` (deployed), `goplus_screen.py` (fetch + rules +
  provenance), NOMOS claim-issuer + trace builder, claim/bond API routes, oracle UI.
- **Reframed:** SPATHA/AGROS planners (`claim_hedge.py`, `bond_treasury.py`).

## Status

0. ✅ Signal verified — GoPlus (NFI disproven).
1. ✅ Branch + `ClaimRegistry` contract + 7 forge tests + deploy script.
2. ✅ Deployed to Arc testnet; `CLAIM_REGISTRY_ADDR` set; orchestrator restarted.
3. ✅ Backend: GoPlus screener → claim-issuer → trace → `issueClaim`; bond writes;
   AGROS/SPATHA planners. Read API `/api/claims` live (`available:true`).
4. ✅ Oracle UI (`/app/oracle`).
5. ⏳ Issue first real claim off a GoPlus-flagged token; backfill a few for the demo.

## Open inputs

- **Gateway source chain** for bonds (which testnet USDC is funded).
- **Token-discovery feed** (watchlist now; DEX new-pairs firehose later).
- Resolution oracle for "did TOKEN drop > threshold?" (price feed / manual resolver
  for the demo; automate later).

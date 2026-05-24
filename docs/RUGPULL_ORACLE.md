# AKRITA Rugpull Oracle — design (Pivot 1 + Gateway)

> Pivot away from Polymarket V2 (no public testnet → execution can't be demoed)
> to a target that runs **end-to-end on testnet today**: a signed, on-chain
> **rug-risk oracle** sourced from the NostalgiaForInfinity (NFI) blacklist feed,
> with a two-sided USDC bond market and cross-chain bond funding via Circle Gateway.
> Reuses ~90% of AKRITA: the trace pipeline, Arc/USYC/Hyperliquid/Gateway adapters,
> BuilderRegistry/ERC-8004, the Risk Agent, and the frontend shell.

## The signal (verified)

`github.com/iterativv/NostalgiaForInfinity` — active freqtrade strategy. Per-exchange
blacklists at `configs/blacklist-<exchange>.json` (binance, bybit, okx, kraken, …,
**hyperliquid**), freqtrade format `{"<exchange>": {"pair_blacklist": ["TOKEN/USDT", …]}}`.
Git-tracked; the project's own `nfi-updater` polls them via HTTP ETag every 60s — so
**every blacklist addition is a real commit/diff** = a per-event, provable signal.
`blacklist-hyperliquid.json` lines up with AKRITA's existing Hyperliquid adapter.

## Product

When a token is added to an NFI blacklist, AKRITA **issues a signed claim**:
"iterativv blacklisted TOKEN at commit `sha` / block N — rug risk." The claim is:
1. serialized to a canonical reasoning trace → sha256 → IPFS → **TraceRegistry on Arc**
   (the existing pipeline, unchanged), and
2. registered in a new **ClaimRegistry** with an optional two-sided **bond market**
   ("will TOKEN drop > threshold within the window?"). Stakers bond USDC for/against;
   on resolution the wrong side is slashed pro-rata to the winners.

The product *is* the trace: a verifiable, on-chain attestation with GitHub provenance.

## Agent remap

| Agent | Was | Now |
|---|---|---|
| **NOMOS** | quoting / market maker | **claim issuer** — watches the NFI blacklist commits, builds the reasoning trace (provenance + credibility), anchors it, calls `issueClaim`. |
| **SPATHA** | Polymarket inventory hedger | **exposure hedger** — same Hyperliquid adapter, hedges directional risk on issued claims. |
| **AGROS** | treasury | **bond treasury** — holds idle bond capital in USYC between events; bond pool on Arc is funded cross-chain via **Gateway**. |

## ClaimRegistry contract (Arc)

Minimal, no-OpenZeppelin, matches TraceRegistry style. `owner` + `authorizedIssuers`
(NOMOS keeper) + `authorizedResolvers`. Per claim: `tokenId` (keccak of
`TOKEN/QUOTE@exchange`), `sourceCommit` (NFI git sha), `traceHash` (→ TraceRegistry),
`ipfsCid`, `window`, `dropThresholdBps`, `status`. Bond market: `stake(claimId,
backsClaim, amount)` (USDC `transferFrom`), `resolve(claimId, rugged)` (resolver),
`withdraw(claimId)` (winners get stake + pro-rata of the losing pool; losers slashed;
idempotent). Trace anchoring stays in `TraceRegistry` — the two contracts compose.

## Gateway bond flow (load-bearing Circle usage)

Bond capital originates as USDC on an EVM source testnet → **Gateway** (deposit → burn
intent → mint) → the Arc bond pool. AGROS parks idle bonds in USYC and routes inflows
via the existing `GatewayReal` adapter. Source chain is config-driven
(`bond_source_chain` / `bond_source_domain`); set it to whichever testnet is funded.

## Reuse map

- **Unchanged:** trace pipeline, `ArcReal`, `USYCReal` (allowlisted), `HyperliquidReal`
  (reads), `GatewayReal`, BuilderRegistry/ERC-8004, frontend shell, canonical hashing.
- **New:** `ClaimRegistry.sol` (+ deploy script), NFI blacklist watcher, NOMOS
  claim-issuer decision type + trace builder, claim/bond API routes, frontend reframe.
- **Reframed:** Risk Agent gets claim-issuance checks; SPATHA/AGROS narratives.

## Phases

0. ✅ Verify signal — done.
1. Branch `feat/rugpull-oracle` + this doc + `ClaimRegistry` contract & tests.
2. Deploy script + (gated) Arc deploy.
3. Backend: NFI watcher → claim-issuer (NOMOS) → trace → `issueClaim`; bond routes;
   AGROS Gateway bond inflow; SPATHA exposure read.
4. Frontend reframe (oracle feed / claims / bonds) on the existing shell.
5. Demo: backfill historical blacklist commits; full testnet run.

## Open inputs

- **Gateway source chain** for bonds (which testnet USDC is funded).
- Resolution oracle for "did TOKEN drop > threshold?" (price feed / manual resolver for
  the demo; automate later).

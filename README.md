# AKRITA

> **Three signed AI agents that watch the chain for fraud, issue verifiable rug-risk claims, and run a permissionless USDC bond market — every decision hashed and anchored on Arc, so nothing has to be taken on trust.**

**Live:** [akritafi.xyz](https://akritafi.xyz)

---

## What is AKRITA?

AKRITA is an **autonomous, on-chain rug-risk oracle**. It continuously reads real fraud signals from the blockchain — stablecoin issuer freezes (USDT/USDC blacklisting), GoPlus token-security failures (honeypots, hidden owners, mint backdoors), and tokens it discovers on its own from the open market — reasons about each one with an LLM behind a deterministic safety gate, and **issues a signed claim**:

> *"TOKEN was flagged by GoPlus (honeypot · owner-can-mint) — rug risk."*

Each claim is committed as a **verifiable reasoning trace**: canonical JSON → `sha256` → IPFS → on-chain registry on Arc. Because the hashing is deterministic and the source data is reproducible, **anyone can re-derive the on-chain hash from the original signal** — the product *is* the proof.

On top of each predictive claim sits a **two-sided USDC bond market**: anyone can stake *for* ("it rugs") or *against* ("it's safe"). When the outcome is clear, the claim resolves and the losing side is slashed pro-rata to the winners.

### Why it matters

On-chain fraud signals already exist, but they're scattered, opaque, and unaccountable — you have to *trust* whoever is screaming "scam." AKRITA turns that into an **accountable oracle**: every call is timestamped, reasoned, signed, and anchored *before* anyone can act on it, with a market that puts real capital behind every prediction. Don't trust the call — verify it, then bet against it if you disagree.

---

## How a claim flows

```
  On-chain Signal  ─►  Claim + Hash  ─►  IPFS Pin  ─►  Arc Anchor  ─►  Resolve
  (freeze / GoPlus     (canonical        (CID, full     (TraceRegistry   (AGROS settles
   / self-discovery)    JSON → sha256)    trace body)    + ClaimRegistry)  the bond market)
```

1. **Signal** — a stablecoin issuer freezes an address, or GoPlus flags a token, or NOMOS discovers a freshly-promoted token (via DEXScreener) and triages it.
2. **Claim + hash** — NOMOS builds a reasoning trace (the flags, the LLM rationale, the GoPlus provenance) and fingerprints it with `sha256` of its canonical JSON.
3. **IPFS pin** — the full trace body is pinned (paid via Circle Nanopayments) and addressed by CID.
4. **Arc anchor** — the hash + claim are committed to the on-chain `TraceRegistry` + `ClaimRegistry` on Arc (gas paid in USDC, ~$0.01).
5. **Resolve** — AGROS checks the token's real market and settles the bond; winners withdraw their stake plus a share of the losing pool.

---

## The three agents

AKRITA runs three **signed autonomous agents**, gated by a deterministic **Risk Agent**, each with a distinct mandate. Their names come from the Byzantine *akritai* — the frontier-keepers who farmed productive land until the moment they had to defend it.

| Agent | Greek | Role | What it does |
|---|---|---|---|
| **NOMOS** | νόμος — *the law inscribed* | **Claim issuer** | Reads on-chain rug signals, reasons with an LLM under the risk gate, and issues a signed rug-risk claim — anchoring trace + provenance on Arc. |
| **SPATHA** | σπάθα — *the cut at the boundary* | **Risk sentinel** | Forms an *independent* second opinion on each claim (back / fade / abstain) and stakes its conviction on-chain as agent 2. |
| **AGROS** | ἀγρός — *the field that yields* | **Treasury / resolver** | Settles bonds when the outcome is clear, and keeps idle bond capital productive in **USYC** between events. |

The agents run autonomously on a schedule and **never act blindly**: the deterministic Risk Gate must pass before anything is written, and the LLM's reasoning is committed *into* the on-chain trace — so you can read exactly *why* a claim exists.

---

## What's verifiable

The heart of AKRITA is the **reasoning trace**. Every decision is serialized to a canonical, whitespace-free, key-sorted JSON (JCS / RFC-8785-inspired) and hashed:

```
trace_hash = "0x" + sha256( canonical_json(trace_body) ).hexdigest()
```

That exact hash is what the on-chain `commitTrace` stores and what `verifyTrace` recomputes. The trace body carries the **facts** (`fundamentals`), the **reasoning** (`technical`), the **conclusion**, the full **risk-gate verdict**, and the **model** that decided. Anyone can:

1. Fetch the trace body from IPFS by its CID,
2. Re-run the canonical hash,
3. Compare it against the value anchored on Arc.

The Trust Layer page renders this as a 4-step verification certificate — *fetch from IPFS → hash → check the Arc registry → seal*. This is how "don't trust, verify" actually works.

---

## The bond market

Each predictive claim carries an optional two-sided USDC bond market — *"will TOKEN drop more than the threshold within the window?"*:

- **Stake** — bond USDC for ("it rugs") or against ("it's safe") the claim.
- **Resolve** — an authorized resolver records the real outcome.
- **Withdraw** — winners reclaim their stake plus a pro-rata share of the losing pool; losers are slashed.

Bond capital can originate as USDC on any EVM chain and be routed to the Arc bond pool **cross-chain via Circle Gateway**. Staking is **permissionless** — connect any wallet on the Oracle page and back or fade a call.

---

## Architecture

```
                       ┌────────────────────────────────────────────────┐
   GoPlus API     ◄────►│            AKRITA Orchestrator (BFF)           │◄───► Hyperliquid (reads)
   Stablecoin freezes   │  FastAPI · nonce gate · Risk Agent (12 checks) │
   DEXScreener feed     │  · LLM reasoner · trace pipeline · adapters    │◄───► USYC / Circle Gateway
                        │                                                │
   NOMOS ─┐             │   canonical JSON ─► sha256 ─► IPFS (pinned) ───┼───► Arc L1 (USDC gas)
   SPATHA ─┼──decisions─►                          └─► TraceRegistry ────┼──►  · TraceRegistry
   AGROS ─┘             │                              ClaimRegistry ────┼──►  · ClaimRegistry
                        │   Postgres (state) · Redis (nonces/ids)        │     · BuilderRegistry
                        └────────────────────────────────────────────────┘
                                          ▲
                              static frontend (served by FastAPI)
```

**Per-decision lifecycle** — every agent action flows through one path: claim a **nonce** → pass the deterministic **Risk Gate** → build the **trace sections** → **commit the trace to Arc** *before* any execution → execute (with a kill-switch and a hard per-action cap) → **persist + broadcast** over WebSocket.

---

## Tech stack

- **Backend:** Python 3.12 · FastAPI + Uvicorn · SQLAlchemy 2 (async) over **Postgres** · **Redis** · Pydantic v2
- **Web3:** `web3` v7 · Circle Developer-Controlled **MPC wallets** for signing
- **Contracts:** Solidity `^0.8.24` + Foundry (no OpenZeppelin)
- **LLM:** provider-agnostic reasoner; the deciding model is recorded in every trace
- **Frontend:** plain static HTML + one CSS + vanilla JS — **no framework, no build step**
- **Circle integrations:** **Arc** L1 (USDC as native gas) · **MPC Wallets** · **Nanopayments** (IPFS pinning) · **Gateway** (cross-chain USDC bond funding) · **USYC** (tokenized treasury yield)
- **External signals:** GoPlus Token Security API · stablecoin freeze events · DEXScreener

---

## Smart contracts

Solidity `^0.8.24`,  the same minimal owner + authorized-mapping style across all four.

| Contract | Role | Address |
|---|---|---|
| **ClaimRegistry** | Rug-risk claims + two-sided USDC bond market (stake / resolve / withdraw + slashing) | `0x16aD24beEBa619f7b8C2fcFDa1F1ec1f6210F405` |
| **TraceRegistry** | Append-only log of decision hashes + IPFS CIDs; `commitTrace` / `verifyTrace` | `0xd96C3bf812C18Bb16CD6C73F0BD96960BF609Ea4` |
| **BuilderRegistry** | Maps agents → builder codes + ERC-8004 reputation | `0x060C6E966e4D6Ea11f09916963B59425B18fc223` |
| **SusdeAcceptance** | EIP-712 consent registry for AGROS Tier-C sUSDe cooldown | — |

---

## The name

AKRITA evokes the Byzantine *akritai* — frontier-keepers under the *stratiotika ktemata* (military-lands) system: capital productive by default, instantly pivoting to defense. The visual identity is a "refined Byzantine" parchment / gold / ink aesthetic with Greek titling. More in [docs/BRAND.md](docs/BRAND.md).

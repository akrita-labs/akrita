# AKRITA — Brand & Conceptual Framework

> *"The soldier holds the plow and the spatha in turn."*

## 1. The name

**AKRITA** [uh-KREE-tuh / ah-KREE-tah]. Three syllables; single word; reads identically in English and Spanish.

From the Greek *akra* (ἄκρα) — the edge, the frontier, the territorial limit. The *akritai* (ἀκρῖται) were the frontier soldiers of the medieval Byzantine empire who held the eastern marches against Arab and Turkic incursions from the 7th through 11th centuries.

We deliberately rejected the placeholder name *Hephaestus-Prime* (and similar exhausted-deity formats: Apollo, Hermes, Athena). The brand thesis is **historical institutional engineering** — a name from a documented imperial reform program, not a god-of-fire grab-bag.

## 2. The historical metaphor

To solve a chronic insolvency of the central treasury under pressure from a vast, volatile frontier, the Byzantine empire implemented the *Stratiotika Ktemata* (Στρατιωτικά κτήματα — "Military Lands") system. Soldiers were granted productive agricultural plots **inside the frontier zones themselves**. By default they were farmers — they tilled, harvested, and made the land economically productive during peacetime. At the moment of an incursion, the same individuals transformed instantly into heavy cavalry, drawing the *spatha* and riding to the breach.

The system worked because:
1. Capital (the land) was productive by default, not idle and waiting.
2. The transition from productive use to defensive use was instant (the akritai were already on-site, already armed).
3. The economic surplus from the farming directly funded the military readiness.

AKRITA is the protocol-level instantiation of this doctrine. The market-making capital is the land; USYC is the harvest; the inventory threshold is the alarm horn; SPATHA's perp position is the cavalry charge.

This is not a generic LLM-wrapper trading bot dressed up in classical aesthetics. It is a deliberate algorithmic replica of a real, documented institutional engineering program.

## 3. The agent triumvirate

Each agent's name maps to its operational role through Greek etymology, not theology:

### NOMOS (νόμος) — Pricing
**The norm. The decree. The geometric demarcation of territory.**

NOMOS is the protocol-frontier law. It selects Polymarket V2 markets to quote, sets the bid/ask spread on both sides of the book, and structures the order layers to maximize builder-code attribution capture while staying inside policy bounds. It is the agent that "draws the line on the map" — establishing where AKRITA stands in the orderbook.

Its decisions are quote pairs, signed EIP-712, submitted continuously.

### SPATHA (σπάθα) — Hedge
**The heavy double-edged cavalry sword.**

SPATHA is the tactical risk-containment force. It stands watch silently, reading the inventory snapshot AGORS computes. When directional exposure breaches the delta threshold, SPATHA fires a perp position on Hyperliquid that exactly neutralizes the resulting market risk — drawing the sword.

The hedge is a **real directional position on a price-bearing instrument**. Not a stable-to-stable swap, not a synthetic. The akritai cavalry struck flesh; SPATHA opens a perp.

### AGROS (ἀγρός) — Treasury
**The cultivated field. The daily source of the polis's sustenance.**

AGROS is the economic engine. Its mandate is simple: **no dollar shall sit idle**. Every 60 seconds it computes projected outflow, applies a safety multiplier, and sweeps surplus USDC into USYC (the harvest) — or redeems USYC back to USDC when the operational floor is approached. It transforms market-making's operating cost into a continuous positive yield carry.

AGROS is the agent that delivers the project's thesis. Without it, the system reduces to a generic keeper.

## 4. Why the framing matters for the hackathon

Judges score Innovation at 20% of the rubric. "Doing X better" is iteration, not innovation. AKRITA's claim is that **the metaphor itself is the design**: by treating capital the way the empire treated frontier soldiers, we get an architectural pattern (default productive, instantly switchable, on-site capable) that existing keepers don't have because they don't have the conceptual model to organize around.

The pitch advantages this gives us:

1. **Ecosystem synergy** — explicitly stacks Circle's corporate liquidity primitives (USDC + USYC), Arc's autonomous-agent-friendly economics, and the Polymarket V2 builder program in a single coherent thesis.
2. **Memorable framing** — a judge who saw 40 demos will remember "the Byzantine farmer-soldier protocol" specifically, not "another AI keeper."
3. **Cohesive nomenclature** — NOMOS/SPATHA/AGROS reads as one designed system, not three separately-named modules.
4. **Bilingual cleanliness** — the team is fluent in Spanish and English; AKRITA reads identically in both. The pitch translates without semantic drift.

## 5. Visual identity

**Palette:**
- Parchment field (`#ece3cf`) — the document, the dispatch
- Deep navy ink (`#1a2238`) — the imperial seal
- Restrained gold (`#b08a3c`) — accents only; never dominant
- Crimson (`#7a1f1f`) — alarms, breaches, hedge alerts
- Moss (`#4a5f3a`) — yield, growth, the productive field

**Typography:**
- *Display*: Cormorant Garamond — for headers and agent names. Trajan-adjacent classical roman.
- *Body*: Spectral — refined contemporary serif with the right institutional gravity.
- *Mono*: JetBrains Mono — for hashes, transaction IDs, and code.

**Sigil:** a vertical *spatha* crossed with a stylized wheat sheaf — the spear and the plow in equilibrium. See `frontend/index.html` for the inline SVG.

## 6. Tone of voice

For all written materials (writeups, slides, social posts, README):

- **Direct.** No "revolutionary AI-powered" marketing voice.
- **Historical-precise.** When we use Greek/Latin terms, we use them correctly and explain etymology once.
- **Institutional.** This is a financial-infrastructure submission, not a meme project. Sentences should read like a Renaissance banker's ledger annotation, not a startup launch tweet.
- **Bilingual-aware.** Avoid English-only idioms ("game-changer", "next-level", "out of the box"). Stick to language that translates clean.

## 7. The pitch in one paragraph (English)

> A market maker's capital is in one of two states: working or idle. Every existing prediction-market keeper holds idle capital in stablecoins earning zero, which is why the unit economics fail at retail size and why no serious team runs a Polymarket V2 keeper. AKRITA inverts the default — idle capital sits in USYC earning T-bill yield, becomes USDC operating margin only when an order needs to fill. The Treasury Agent (AGROS) sweeps the boundary every 60 seconds. The economics only work on Arc, where sub-second finality plus $0.01 transaction fees plus Gateway's <500ms cross-chain transfer push per-rebalance overhead below the yield differential. Three agents in coordination — NOMOS the pricing-frontier law, SPATHA the cavalry hedge, AGROS the productive field — replicating the Byzantine *Stratiotika Ktemata* doctrine in code. Every decision is committed on-chain through our `TraceRegistry` so post-facto verification is trivial.

## 8. El pitch en un párrafo (Español)

> El capital de un creador de mercado se encuentra en uno de dos estados: trabajando u ocioso. Los keepers actuales de mercados de predicción mantienen el capital ocioso en stablecoins sin generar rendimiento — razón por la cual la economía unitaria falla al tamaño minorista y ningún equipo serio opera un keeper en Polymarket V2. AKRITA invierte el comportamiento por defecto: el capital ocioso reside en USYC obteniendo rendimiento de bonos del tesoro, transformándose en margen operativo en USDC sólo cuando una orden está por ejecutarse. El Agente de Tesorería (AGROS) realiza el barrido de esta frontera cada 60 segundos. La economía sólo es viable en Arc, donde la finalidad sub-segundo, las comisiones de $0.01 y la transferencia cross-chain de Gateway en <500ms reducen el costo de cada rebalanceo por debajo del diferencial de rendimiento. Tres agentes coordinados — NOMOS la ley de la frontera de precios, SPATHA la espada de caballería, AGROS el campo productivo — replicando algorítmicamente la doctrina bizantina de los *Stratiotika Ktemata*. Cada decisión se confirma on-chain mediante nuestro `TraceRegistry`, haciendo trivial la verificación post-hoc.

---

*"Stratiotika ktemata — el soldado sostiene el arado y la spatha por turnos."*

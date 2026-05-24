import { useEffect } from "react";
import ParchmentOverlay from "../components/Layout/ParchmentOverlay";
import Header from "../components/Layout/Header";
import Footer from "../components/Layout/Footer";

export default function AboutPage() {
  useEffect(() => {
    document.body.className = "about-page";
    return () => {
      document.body.className = "";
    };
  }, []);

  return (
    <>
      <ParchmentOverlay />
      
      <Header className="home-header builder-site-header" />

      <main className="about-sheet">
        <section className="about-hero">
          <div className="about-initial" aria-hidden="true">A</div>
          <div>
            <p className="about-kicker">Arc testnet · Agora Agents Hackathon · 2026</p>
            <h1>About AKRITA</h1>
            <p>AKRITA is a frontier-keeper protocol: autonomous agents that keep margin productive until the instant it is needed, then anchor every decision as a verifiable trace.</p>
          </div>
        </section>

        <section className="about-grid">
          <article>
            <span>NOMOS</span>
            <h2>The law of the frontier</h2>
            <p>Prices markets, weighs deterministic signals against context, and writes the quote decree.</p>
          </article>
          <article>
            <span>SPATHA</span>
            <h2>The cut at the boundary</h2>
            <p>Contains exposure, hedges inventory, and keeps risk gates from becoming ornament.</p>
          </article>
          <article>
            <span>AGROS</span>
            <h2>The field that yields</h2>
            <p>Moves idle capital between operating liquidity and USYC so treasury time is not wasted.</p>
          </article>
        </section>

        <section className="about-rulebook">
          <h2>What is preserved</h2>
          <dl>
            <dt>Canonical hash</dt>
            <dd>Each decision is serialized, hashed, and committed before action.</dd>
            <dt>IPFS body</dt>
            <dd>The reasoning body remains inspectable and reproducible.</dd>
            <dt>Arc anchor</dt>
            <dd>The registry keeps the frontier accountable to a public settlement layer.</dd>
            <dt>Builder attribution</dt>
            <dd>Fills can carry builder provenance without hiding the keeper’s reasoning.</dd>
          </dl>
        </section>
      </main>

      <Footer variant="builder" />
    </>
  );
}

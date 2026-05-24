import { useEffect } from "react";
import { Link } from "react-router-dom";
import ParchmentOverlay from "../components/Layout/ParchmentOverlay";
import Header from "../components/Layout/Header";
import Footer from "../components/Layout/Footer";

export default function HomePage() {
  useEffect(() => {
    document.body.className = "home-page";
    return () => {
      document.body.className = "";
    };
  }, []);

  return (
    <>
      <ParchmentOverlay />
      
      <Header />

      <main className="home-shell">
        <section className="hero-copy" aria-labelledby="home-title">
          <p className="home-kicker">Agora Agents Hackathon · Canteen × Circle × Arc · 2026</p>

          <h1 id="home-title" className="home-title" aria-label="Capital that farms when it is not fighting.">
            <span className="illuminated-initial" aria-hidden="true">C</span>
            <span className="title-lines" aria-hidden="true">apital that<br />farms when it<br />is not fighting.</span>
          </h1>

          <p className="hero-text">
            Three autonomous agents — NOMOS, SPATHA, AGROS — keep the frontier.
            Idle collateral sits in USYC earning treasury yield; pUSD margin moves
            only when fills are imminent. Every decision hashed and anchored on Arc.
            A keeper modeled on the Byzantine <em>stratiotika ktemata</em>: capital
            that defends a frontier by remaining productive between engagements.
          </p>

          <div className="home-divider" aria-hidden="true">
            <span></span>
            <b>✠</b>
            <span></span>
          </div>

          <div className="hero-actions" aria-label="Primary actions">
            <Link className="hero-button hero-button-primary" to="/dashboard">View Live Keeper</Link>
            <a 
              className="hero-button hero-button-secondary" 
              href="https://github.com/akrita-labs/akrita/blob/main/docs/ARCHITECTURE.md"
              target="_blank"
              rel="noopener noreferrer"
            >
              Read the Trace Protocol
            </a>
          </div>
        </section>

        <section className="keeper-plate" aria-label="Annotated frontier keeper figure">
          <span className="plate-flower plate-flower-tl" aria-hidden="true">✾</span>
          <span className="plate-flower plate-flower-tr" aria-hidden="true">✾</span>
          <span className="plate-flower plate-flower-bl" aria-hidden="true">✾</span>
          <span className="plate-flower plate-flower-br" aria-hidden="true">✾</span>

          <img 
            className="keeper-figure" 
            src="/assets/frontier-keeper.png" 
            alt="Sepia manuscript illustration of a Byzantine frontier keeper holding a plow and sword." 
          />

          <div className="figure-label label-akrites">
            <span>ΑΚΡΙΤΗΣ —</span>
            <em>the frontier-keeper</em>
          </div>
          <div className="figure-label label-agros">
            <span>ΑΓΡΟΣ —</span>
            <em>the field that yields</em>
          </div>
          <div className="figure-label label-nomos">
            <span>ΝΟΜΟΣ —</span>
            <em>the law inscribed</em>
          </div>
          <div className="figure-label label-spatha">
            <span>ΣΠΑΘΑ —</span>
            <em>the cut at<br />the boundary</em>
          </div>

          <p className="plate-caption">Composite figure after Cappadocia, c. 950 CE</p>
        </section>
      </main>

      <Footer variant="home" />
    </>
  );
}

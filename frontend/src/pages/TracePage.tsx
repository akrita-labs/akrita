import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import ParchmentOverlay from "../components/Layout/ParchmentOverlay";
import DashboardHeader from "../components/Layout/DashboardHeader";
import Footer from "../components/Layout/Footer";
import PanelCorners from "../components/ui/PanelCorners";
import { useLiveSocket } from "../hooks/useLiveSocket";
import { fetchDecisions } from "../api/client";
import type { Decision } from "../api/client";

export default function TracePage() {
  const [searchParams] = useSearchParams();
  const hash = searchParams.get("hash") || "0xa9adcb87b510cde9f4a7b1f2d3c4e5f67890123456789abcdef0123456789abcd";

  const [wsStatus, setWsStatus] = useState<"connecting" | "live" | "disconnected">("disconnected");
  const [matchedDecision, setMatchedDecision] = useState<Decision | null>(null);
  const [loading, setLoading] = useState(true);

  // Subscribe to WebSocket events just to stay active
  const status = useLiveSocket(() => {
    // If we receive a message, re-fetch decisions to see if our trace is now available
    loadDecision();
  });

  useEffect(() => {
    setWsStatus(status);
  }, [status]);

  const loadDecision = async () => {
    try {
      const res = await fetchDecisions(100);
      const dec = res.decisions.find(d => d.trace_hash === hash);
      if (dec) {
        setMatchedDecision(dec);
      } else {
        setMatchedDecision(null);
      }
    } catch (err) {
      console.warn("Failed to load matching decision for trace:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    document.body.className = "trace-page";
    loadDecision();
    return () => {
      document.body.className = "";
    };
  }, [hash]);

  // Fallback / default data (matching trace.html mock data)
  const defaultTraceInfo = {
    agent: "NOMOS",
    decision_id: 12847,
    timestamp: "2026-05-23 14:32:18.123 UTC",
    json: {
      trace_id: hash,
      decision_id: 12847,
      agent: "NOMOS",
      bid: 0.612,
      ask: 0.628,
      size: 100,
      risk_gate: "approved"
    }
  };

  const agentName = matchedDecision ? matchedDecision.agent_role.toUpperCase() : defaultTraceInfo.agent;
  const decisionId = matchedDecision ? matchedDecision.decision_id : defaultTraceInfo.decision_id;
  const timestamp = matchedDecision 
    ? new Date(matchedDecision.ts_ms).toUTCString() 
    : defaultTraceInfo.timestamp;

  const conclusioJson = matchedDecision 
    ? {
        trace_id: hash,
        decision_id: matchedDecision.decision_id,
        agent: matchedDecision.agent_role.toUpperCase(),
        ...(matchedDecision.agent_role === "nomos" && {
          bid: matchedDecision.bid,
          ask: matchedDecision.ask,
          size: matchedDecision.size
        }),
        ...(matchedDecision.agent_role === "spatha" && {
          side: matchedDecision.side,
          size: matchedDecision.size,
          instrument: matchedDecision.instrument
        }),
        ...(matchedDecision.agent_role === "agros" && {
          action: matchedDecision.action,
          amount: matchedDecision.amount
        }),
        risk_gate: "approved"
      }
    : defaultTraceInfo.json;

  return (
    <>
      <ParchmentOverlay />
      
      <DashboardHeader wsStatus={wsStatus} />

      <main className="trace-sheet">
        <PanelCorners prefix="trace" />

        <aside className="trace-marginalia" aria-label="Trace margin notes">
          <p><span>→</span> market is<br />high-volume,<br />FOMC week</p>
          <p><span>→</span> implied<br />probability vs<br />deterministic<br />mid</p>
          <p><span>→</span> news<br />sentiment<br />ingest,<br />3 sources</p>
        </aside>

        <aside className="trace-stamps" aria-label="Trace status">
          <div><span>✓ COMMITTED</span><b>✠</b></div>
          <div><span>✓ PINNED</span><b>⚓</b></div>
          <div><span>✓ VERIFIED</span><b>◉</b></div>
        </aside>

        <section className="trace-document">
          <header className="trace-title-row">
            <div className="trace-initial" aria-hidden="true">
              {agentName.charAt(0) || "T"}
            </div>
            <div>
              <h1>Trace · {hash.slice(0, 14)}...</h1>
              <p><em>agent:</em> {agentName} · <em>decision_id:</em> {decisionId} · <em>ts:</em> {timestamp}</p>
              <div className="trace-title-rule" aria-hidden="true">
                <span></span><b>✠</b><span></span><b>✠</b><span></span><b>✠</b><span></span>
              </div>
            </div>
          </header>

          <section className="trace-block fundamentals-block">
            <div className="trace-medallion scale-medallion" aria-hidden="true"></div>
            <div className="trace-block-body">
              <h2>I. Fundamenta — The Weighing of Facts</h2>
              <table className="trace-facts">
                <tbody>
                  <tr>
                    <th>market.id</th>
                    <td>{matchedDecision?.agent_role === "nomos" ? "0xabc...123" : "0x4f2a...1bcd"}</td>
                  </tr>
                  <tr>
                    <th>market.question</th>
                    <td>
                      {matchedDecision?.agent_role === "spatha" 
                        ? "Hedge execution threshold limit check" 
                        : matchedDecision?.agent_role === "agros"
                        ? "Treasury liquidity and yield optimization harvest"
                        : "Will Fed cut rates by 25bps in June 2026?"}
                    </td>
                  </tr>
                  <tr>
                    <th>implied_prob</th>
                    <td>{matchedDecision?.agent_role === "nomos" ? "0.62" : "—"}</td>
                  </tr>
                  <tr>
                    <th>news_context</th>
                    <td>
                      <span className="tone tone-dovish">Dovish</span> Powell signals patience as inflation shows further signs of easing<br />
                      <span className="tone tone-neutral">Neutral</span> Jobs growth moderates; labor market remains resilient<br />
                      <span className="tone tone-hawkish">Hawkish</span> FOMC officials caution against premature rate cuts
                    </td>
                  </tr>
                  <tr>
                    <th>macro</th>
                    <td>CPI YoY 3.4 · FFR 5.25 · FOMC 2026-06-12</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section className="trace-block technical-block">
            <div className="trace-medallion sextant-medallion" aria-hidden="true"></div>
            <div className="trace-block-body technical-grid">
              <h2>II. Technica — The Measurement of Market</h2>
              <div className="market-gauge">
                <div className="ask-label">ASK</div>
                <div className="bid-label">BID</div>
                <div className="mid-label">mid 0.625</div>
                <div className="gauge-axis" aria-hidden="true"><b>✠</b></div>
                <ol>
                  <li>0.665</li><li>0.650</li><li>0.640</li><li>0.630</li>
                  <li>0.620</li><li>0.610</li><li>0.600</li><li>0.590</li>
                </ol>
              </div>
              <dl className="technical-readout">
                <dt>deterministic_mid:</dt>
                <dd>0.625</dd>
                <dt>llm_bid_delta_bps:</dt>
                <dd>-15</dd>
                <dt>llm_ask_delta_bps:</dt>
                <dd>+20</dd>
                <dt>rationale:</dt>
                <dd>
                  {matchedDecision?.agent_role === "nomos" 
                    ? "Dovish Reuters headline tilts probability higher. Headline parsed at 14:32:14, weighted 0.7 of total context vector..." 
                    : matchedDecision?.agent_role === "spatha"
                    ? "Spatha monitored limits. Delta position threshold exceeded. Initiated partial hedging transaction."
                    : matchedDecision?.agent_role === "agros"
                    ? "Agros scan yield curves. USYC yield premium is 4.13%. Commencing deposit sweep."
                    : "Dovish Reuters headline tilts probability higher. Headline parsed at 14:32:14, weighted 0.7 of total context vector..."}
                </dd>
              </dl>
            </div>
          </section>

          <section className="trace-block conclusion-block">
            <div className="trace-medallion ring-medallion" aria-hidden="true"></div>
            <div className="trace-block-body">
              <h2>III. Conclusio — The Decree Enacted</h2>
              <pre>{JSON.stringify(conclusioJson, null, 2)}</pre>
            </div>
          </section>
        </section>
      </main>

      <Footer variant="trace" />
    </>
  );
}

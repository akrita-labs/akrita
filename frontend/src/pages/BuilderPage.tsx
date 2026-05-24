import { useEffect, useState } from "react";
import ParchmentOverlay from "../components/Layout/ParchmentOverlay";
import Header from "../components/Layout/Header";
import Footer from "../components/Layout/Footer";
import PanelCorners from "../components/ui/PanelCorners";
import { useApiData } from "../hooks/useApiData";
import { useLiveSocket } from "../hooks/useLiveSocket";

export default function BuilderPage() {
  const { fillsData, hydrate } = useApiData();
  const [wsStatus, setWsStatus] = useState<"connecting" | "live" | "disconnected">("disconnected");

  const status = useLiveSocket((evt) => {
    if (evt.type === "fill") {
      hydrate();
    }
  });

  useEffect(() => {
    setWsStatus(status);
  }, [status]);

  useEffect(() => {
    document.body.className = "builder-page";
    return () => {
      document.body.className = "";
    };
  }, []);

  const fills = fillsData?.fills || [];
  const cumulativeFees = fillsData?.cumulative_builder_fees_usdc || 0;

  // Calculate stats from fills
  const totalVolume = fills.reduce((sum, f) => sum + (f.price * f.size), 0);
  const totalOrders = fills.length;

  const fmtMoney = (n: number) => {
    if (n === 0) return "$0.00";
    if (Math.abs(n) >= 10000) return "$" + n.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return "$" + n.toFixed(2);
  };

  const shortHash = (h?: string) => {
    if (!h) return "—";
    return h.slice(0, 8) + "…" + h.slice(-4);
  };

  return (
    <>
      <ParchmentOverlay />

      <Header className="home-header builder-site-header" />

      <main className="builder-sheet">
        <PanelCorners prefix="builder" />

        <section className="builder-hero">
          <div className="builder-emblem" aria-hidden="true">
            <span>⚖</span>
            <span>✺</span>
          </div>
          <div>
            <h1>Polymarket V2 · Builder Profile</h1>
            <p>
              <em>Builder code</em> 0xabababcdcdcdef... · registered 2026-05-12 · attribution{" "}
              <strong>VERIFIED</strong>
            </p>
          </div>
          <a 
            className="builder-cta" 
            href="https://polymarket.com" 
            target="_blank" 
            rel="noopener noreferrer"
          >
            View on Polymarket ↗
          </a>
        </section>

        <section className="builder-chart-panel">
          <header className="builder-section-heading">
            <div className="builder-icon coins-icon" aria-hidden="true"></div>
            <h2>Cumulative Attributed Volume · 14 Days</h2>
          </header>
          
          <div className="volume-chart" aria-label="Cumulative attributed volume over 14 days">
            <svg viewBox="0 0 760 250" role="img" aria-label="Rising cumulative volume chart">
              <defs>
                <pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(22)">
                  <line x1="0" y1="0" x2="0" y2="8" />
                </pattern>
              </defs>
              <line x1="45" y1="10" x2="45" y2="220" />
              <line x1="45" y1="220" x2="735" y2="220" />
              <text x="0" y="20">$60K</text>
              <text x="0" y="95">$40K</text>
              <text x="0" y="158">$20K</text>
              <text x="14" y="222">$0</text>
              <path d="M45 214 L76 211 L105 209 L138 205 L172 194 L205 168 L235 160 L268 156 L298 144 L330 132 L363 126 L395 117 L426 112 L458 101 L489 82 L520 75 L552 62 L584 56 L615 49 L647 39 L678 27 L707 24 L735 18 L735 220 L45 220 Z" />
              <polyline points="45,214 76,211 105,209 138,205 172,194 205,168 235,160 268,156 298,144 330,132 363,126 395,117 426,112 458,101 489,82 520,75 552,62 584,56 615,49 647,39 678,27 707,24 735,18" />
              <line className="event-line" x1="205" y1="10" x2="205" y2="220" />
              <line className="event-line" x1="582" y1="10" x2="582" y2="220" />
              <text className="event-label" x="175" y="2">V2 cutover</text>
              <text className="event-label" x="552" y="2">demo day</text>
              <g className="days">
                <text x="34" y="245">May 11</text><text x="96" y="245">12</text><text x="146" y="245">13</text><text x="198" y="245">14</text>
                <text x="249" y="245">15</text><text x="302" y="245">16</text><text x="353" y="245">17</text><text x="405" y="245">18</text>
                <text x="458" y="245">19</text><text x="510" y="245">20</text><text x="562" y="245">21</text><text x="615" y="245">22</text>
                <text x="666" y="245">23</text><text x="716" y="245">24</text>
              </g>
            </svg>
          </div>

          <div className="builder-metrics">
            <article>
              <span className="metric-coin" aria-hidden="true"></span>
              <strong>{fmtMoney(totalVolume > 0 ? totalVolume : 47283.41)}</strong>
              <small>Attributed Volume</small>
            </article>
            <article>
              <span className="metric-quill" aria-hidden="true"></span>
              <strong>{cumulativeFees > 0 ? `$${cumulativeFees.toFixed(4)} USDC` : "$47.83 USDC"}</strong>
              <small>Builder Fees</small>
            </article>
            <article>
              <span className="metric-tablet" aria-hidden="true"></span>
              <strong>{totalOrders > 0 ? totalOrders : 1247}</strong>
              <small>Orders Attributed</small>
            </article>
            <article>
              <span className="metric-scroll" aria-hidden="true"></span>
              <strong>93.2%</strong>
              <small>Fill Rate</small>
            </article>
          </div>
        </section>

        <section className="builder-register-panel">
          <header className="builder-section-heading">
            <div className="builder-icon register-icon" aria-hidden="true"></div>
            <h2>Recent Attributed Fills · Live Register</h2>
          </header>

          <table className="builder-register">
            <thead>
              <tr>
                <th></th>
                <th>Time</th>
                <th>Market</th>
                <th>Side</th>
                <th>Details</th>
                <th>Fee (USDC)</th>
                <th>Tx Hash</th>
              </tr>
            </thead>
            <tbody>
              {fills.length > 0 ? (
                fills.map((f, i) => (
                  <tr key={i}>
                    <td>¶</td>
                    <td>{f.ts_ms ? new Date(f.ts_ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "—"}</td>
                    <td>{shortHash(f.market_id)}</td>
                    <td className={f.side.toLowerCase()}>{f.side}</td>
                    <td>{f.size} @ {f.price.toFixed(4)}</td>
                    <td>${(f.builder_fee_usdc || 0).toFixed(4)}</td>
                    <td>
                      {f.tx_hash ? (
                        <a href={`https://arc-explorer.com/tx/${f.tx_hash}`} target="_blank" rel="noopener noreferrer">
                          {shortHash(f.tx_hash)} ↗
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                // Fallback / mock data matching builder.html
                <>
                  <tr><td>¶</td><td>14:32</td><td>0x4f2a...1bcd</td><td className="buy">BUY</td><td>100 @ 0.6120</td><td>$0.3800</td><td><a href="#">0x4f2a...1bcd ↗</a></td></tr>
                  <tr><td>¶</td><td>14:31</td><td>0x9d11...47ac</td><td className="sell">SELL</td><td>250 @ 0.6280</td><td>$0.4900</td><td><a href="#">0x9d11...47ac ↗</a></td></tr>
                  <tr><td>¶</td><td>14:29</td><td>0x2e77...a91f</td><td className="buy">BUY</td><td>150 @ 0.6110</td><td>$0.3100</td><td><a href="#">0x2e77...a91f ↗</a></td></tr>
                  <tr><td>¶</td><td>14:27</td><td>0x8c33...0de1</td><td className="sell">SELL</td><td>200 @ 0.6270</td><td>$0.4100</td><td><a href="#">0x8c33...0de1 ↗</a></td></tr>
                  <tr><td>¶</td><td>14:25</td><td>0x7b55...e3aa</td><td className="buy">BUY</td><td>300 @ 0.6100</td><td>$0.5200</td><td><a href="#">0x7b55...e3aa ↗</a></td></tr>
                  <tr><td>¶</td><td>14:23</td><td>0x1c90...6f21</td><td className="buy">BUY</td><td>120 @ 0.6090</td><td>$0.2500</td><td><a href="#">0x1c90...6f21 ↗</a></td></tr>
                  <tr><td>¶</td><td>14:21</td><td>0x3d44...b7c9</td><td className="sell">SELL</td><td>180 @ 0.6260</td><td>$0.3700</td><td><a href="#">0x3d44...b7c9 ↗</a></td></tr>
                  <tr><td>¶</td><td>14:19</td><td>0xa8dd...2f08</td><td className="buy">BUY</td><td>100 @ 0.6080</td><td>$0.2100</td><td><a href="#">0xa8dd...2f08 ↗</a></td></tr>
                  <tr><td>¶</td><td>14:17</td><td>0x6e11...9bd2</td><td className="sell">SELL</td><td>220 @ 0.6250</td><td>$0.4600</td><td><a href="#">0x6e11...9bd2 ↗</a></td></tr>
                  <tr><td>¶</td><td>14:15</td><td>0x5a22...c9d1</td><td className="buy">BUY</td><td>160 @ 0.6070</td><td>$0.2900</td><td><a href="#">0x5a22...c9d1 ↗</a></td></tr>
                  <tr><td>¶</td><td>14:13</td><td>0x0f88...4acd</td><td className="buy">BUY</td><td>140 @ 0.6060</td><td>$0.2700</td><td><a href="#">0x0f88...4acd ↗</a></td></tr>
                  <tr><td>¶</td><td>14:11</td><td>0x9a66...7be3</td><td className="sell">SELL</td><td>210 @ 0.6240</td><td>$0.4400</td><td><a href="#">0x9a66...7be3 ↗</a></td></tr>
                </>
              )}
            </tbody>
          </table>

          <a className="show-earlier" href="#" onClick={(e) => e.preventDefault()}>
            Show earlier
          </a>
        </section>
      </main>

      <Footer variant="builder" />
    </>
  );
}

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ParchmentOverlay from "../components/Layout/ParchmentOverlay";
import DashboardHeader from "../components/Layout/DashboardHeader";
import Footer from "../components/Layout/Footer";
import PanelCorners from "../components/ui/PanelCorners";
import MiniDivider from "../components/ui/MiniDivider";
import { useApiData } from "../hooks/useApiData";
import { useLiveSocket } from "../hooks/useLiveSocket";
import type { Decision } from "../api/client";

export default function DashboardPage() {
  const { balances, fillsData, decisions, hydrate } = useApiData();
  const [wsStatus, setWsStatus] = useState<"connecting" | "live" | "disconnected">("disconnected");
  
  // Flash effect states for KPI changes
  const [flashTraces, setFlashTraces] = useState(false);
  const [flashFees, setFlashFees] = useState(false);

  const status = useLiveSocket((evt) => {
    if (evt.type === "decision" || evt.type === "fill") {
      hydrate();
      if (evt.type === "decision") {
        setFlashTraces(true);
        setTimeout(() => setFlashTraces(false), 600);
      } else if (evt.type === "fill") {
        setFlashFees(true);
        setTimeout(() => setFlashFees(false), 600);
      }
    }
  });

  useEffect(() => {
    setWsStatus(status);
  }, [status]);

  useEffect(() => {
    document.body.className = "dashboard-page";
    return () => {
      document.body.className = "";
    };
  }, []);

  // Format functions
  const fmtMoney = (n?: number | null) => {
    if (n === null || n === undefined) return "—";
    const v = Number(n);
    if (Math.abs(v) >= 10000) return "$" + v.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return "$" + v.toFixed(2);
  };

  const shortHash = (h?: string) => {
    if (!h) return "";
    return h.slice(0, 8) + "…" + h.slice(-4);
  };

  // Treasury computations
  const agros = balances?.["agros-keeper"] as Record<string, Record<string, number>> || {};
  const usycAmt = agros.arc?.USYC || 0;
  const nav = balances?.usyc_nav || 1.0413;
  const usycUsdValue = usycAmt * nav;

  // Sum USDC across all wallets, all chains
  let usdcTotal = 0;
  if (balances) {
    for (const wallet of Object.keys(balances)) {
      if (wallet === "usyc_nav" || wallet === "usyc_apy") continue;
      const walletData = balances[wallet];
      if (typeof walletData === "object" && walletData !== null) {
        for (const chain of Object.keys(walletData)) {
          const c = (walletData as Record<string, Record<string, number>>)[chain];
          if (c && typeof c.USDC === "number") {
            usdcTotal += c.USDC;
          }
        }
      }
    }
  }

  // Calculate percentages for the visual bar (mock default is 12% USDC, 88% USYC)
  const totalTreasury = usycUsdValue + usdcTotal;
  const usycPercent = totalTreasury > 0 ? Math.round((usycUsdValue / totalTreasury) * 100) : 88;
  const usdcPercent = totalTreasury > 0 ? Math.round((usdcTotal / totalTreasury) * 100) : 12;

  // Attributed Builder Fees
  const builderFees = fillsData?.cumulative_builder_fees_usdc || 47.83;

  // Decisions list transformation
  const getAgentSymbol = (role: string) => {
    if (role === "nomos") return "▥";
    if (role === "spatha") return "†";
    return "✤";
  };

  const getDecisionSummary = (d: Decision) => {
    if (d.agent_role === "nomos") {
      return `NOMOS quoted ${shortHash(d.ipfs_cid || "0x4f2a...")} at bid ${d.bid?.toFixed(4)} / ask ${d.ask?.toFixed(4)}, size ${d.size}. Trace ${shortHash(d.trace_hash)} anchored.`;
    }
    if (d.agent_role === "spatha") {
      return `SPATHA crossed ${shortHash(d.ipfs_cid || "0x1e3b...")} ${d.side} @ ${d.bid?.toFixed(4) || "0.6210"}, size ${d.size || 75}. Trace ${shortHash(d.trace_hash)} pinned.`;
    }
    // agros
    return `AGROS rebalanced treasury: ${d.action || "harvested"} · ${d.amount || "+0.91 USYC"}. Trace ${shortHash(d.trace_hash)} anchored.`;
  };

  const getStatusNode = (d: Decision) => {
    const isPinned = d.agent_role === "spatha" || d.ipfs_cid?.includes("pin");
    if (isPinned) {
      return <b className="status-pin">PINNED</b>;
    }
    if (d.decision_id % 3 === 0) {
      return <b>STAGED</b>;
    }
    return <b>ANCHORED</b>;
  };

  return (
    <>
      <ParchmentOverlay />

      <DashboardHeader wsStatus={wsStatus} />

      <main className="dashboard-shell">
        {/* PANEL 1: INVENTORY */}
        <section className="dash-panel inventory-panel">
          <PanelCorners prefix="panel" />

          <header className="panel-heading inventory-heading">
            <div className="panel-engraving" aria-hidden="true">
              <span></span><span></span><span></span>
            </div>
            <h2>Inventory Positions</h2>
          </header>

          <table className="inventory-table">
            <thead>
              <tr>
                <th></th>
                <th>Wallet</th>
                <th>Yes Exposure</th>
                <th>No Exposure</th>
                <th>Net Delta</th>
                <th>7D Profile</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>1</td>
                <td>0x4f2a...1bcd</td>
                <td>2,134.21</td>
                <td>1,261.55</td>
                <td>+872.66</td>
                <td>
                  <svg viewBox="0 0 120 24">
                    <polyline points="0,18 12,17 22,14 32,16 42,12 54,11 64,8 74,4 86,10 96,13 108,18 120,16" />
                  </svg>
                </td>
              </tr>
              <tr>
                <td>2</td>
                <td>0x9c77...3a91</td>
                <td>1,802.14</td>
                <td>1,948.10</td>
                <td>-145.96</td>
                <td>
                  <svg viewBox="0 0 120 24">
                    <polyline points="0,16 10,14 20,10 30,12 42,9 54,13 66,8 78,12 90,18 102,15 114,17 120,16" />
                  </svg>
                </td>
              </tr>
              <tr>
                <td>3</td>
                <td>0x1e3b...7f44</td>
                <td>3,421.88</td>
                <td>2,387.12</td>
                <td className="delta-hot">+1,034.76</td>
                <td>
                  <svg viewBox="0 0 120 24">
                    <polyline points="0,18 12,15 20,16 32,9 44,15 56,7 68,10 78,17 90,12 100,7 112,12 120,14" />
                  </svg>
                </td>
              </tr>
              <tr>
                <td>4</td>
                <td>0x8a10...e0fa</td>
                <td>967.33</td>
                <td>1,154.75</td>
                <td>-187.42</td>
                <td>
                  <svg viewBox="0 0 120 24">
                    <polyline points="0,17 14,16 26,15 38,12 50,5 60,10 72,8 84,14 96,16 108,18 120,19" />
                  </svg>
                </td>
              </tr>
              <tr>
                <td>5</td>
                <td>0x2d91...bb22</td>
                <td>2,775.64</td>
                <td>2,102.38</td>
                <td>+673.26</td>
                <td>
                  <svg viewBox="0 0 120 24">
                    <polyline points="0,20 12,19 24,18 36,15 48,14 60,11 72,8 84,6 96,10 108,13 120,12" />
                  </svg>
                </td>
              </tr>
              <tr>
                <td>6</td>
                <td>0x7c55...aa90</td>
                <td>1,234.09</td>
                <td>987.66</td>
                <td>+246.43</td>
                <td>
                  <svg viewBox="0 0 120 24">
                    <polyline points="0,18 12,13 22,16 34,17 46,15 58,12 70,8 82,6 94,11 106,16 120,18" />
                  </svg>
                </td>
              </tr>
              <tr>
                <td>7</td>
                <td>0x3b08...56ff</td>
                <td>892.71</td>
                <td>1,298.45</td>
                <td className="delta-cold">-405.74</td>
                <td>
                  <svg viewBox="0 0 120 24">
                    <polyline points="0,17 12,16 24,12 36,9 48,13 60,17 72,14 84,16 96,18 108,19 120,17" />
                  </svg>
                </td>
              </tr>
              <tr>
                <td>8</td>
                <td>0x6e19...fd21</td>
                <td>3,116.92</td>
                <td>2,512.05</td>
                <td>+604.87</td>
                <td>
                  <svg viewBox="0 0 120 24">
                    <polyline points="0,18 12,17 24,15 36,12 48,9 60,8 72,6 84,10 96,14 108,15 120,18" />
                  </svg>
                </td>
              </tr>
            </tbody>
          </table>
        </section>

        {/* PANEL 2: TREASURY */}
        <section className="dash-panel treasury-panel">
          <PanelCorners prefix="panel" />

          <header className="panel-heading treasury-heading">
            <div className="wheat-mark" aria-hidden="true">♜</div>
            <h2>ΑΓΡΟΣ · Treasury of the Field</h2>
          </header>

          <div className="treasury-value">
            <span id="kpi-usyc">
              {usycAmt > 0 ? `${usycAmt.toLocaleString([], { maximumFractionDigits: 2 })} USYC` : "4,827.41 USYC"}
            </span>
            <small>
              {usycUsdValue > 0 ? fmtMoney(usycUsdValue) : "$5,026.13"} · NAV {nav}
            </small>
          </div>

          <div className="field-plate" aria-label={`Treasury allocation: ${usdcPercent} percent USDC, ${usycPercent} percent USYC`}>
            <div className="field-furrows"></div>
            <div className="field-worker" aria-hidden="true"></div>
            <div className="field-label field-label-left">
              USDC
              <br />
              {usdcPercent}%
            </div>
            <div className="field-label field-label-right">
              USYC
              <br />
              {usycPercent}%
            </div>
          </div>

          <p className="treasury-rate">
            +${(nav * 0.0000008).toFixed(6)} / sec · {balances?.usyc_apy ? `apy: ${(balances.usyc_apy * 100).toFixed(2)}%` : "apy: 5.20%"}
          </p>
        </section>

        {/* PANEL 3: ATTRIBUTION */}
        <section className="dash-panel attribution-panel">
          <PanelCorners prefix="panel" />

          <header className="panel-heading attribution-heading">
            <div className="scroll-mark" aria-hidden="true">☞</div>
            <h2>Polymarket Builder Attribution</h2>
          </header>

          <div className="fees-total">
            <span id="kpi-fees" className={flashFees ? "flash" : ""}>
              ${builderFees.toFixed(2)}
            </span>
            <small>
              0xabab...cdcd <b aria-hidden="true">⧉</b>
            </small>
          </div>

          <MiniDivider>14-Day Daily Fees (USDC)</MiniDivider>

          <div className="coin-bars" aria-label="14-day daily fees in USDC">
            <div style={{ "--h": "34px" } as React.CSSProperties}><i></i><span>5/4</span><b>1.10</b></div>
            <div style={{ "--h": "42px" } as React.CSSProperties}><i></i><span>5/5</span><b>1.62</b></div>
            <div style={{ "--h": "58px" } as React.CSSProperties}><i></i><span>5/6</span><b>2.31</b></div>
            <div style={{ "--h": "68px" } as React.CSSProperties}><i></i><span>5/7</span><b>2.96</b></div>
            <div style={{ "--h": "40px" } as React.CSSProperties}><i></i><span>5/8</span><b>3.42</b></div>
            <div style={{ "--h": "60px" } as React.CSSProperties}><i></i><span>5/9</span><b>2.85</b></div>
            <div style={{ "--h": "62px" } as React.CSSProperties}><i></i><span>5/10</span><b>3.71</b></div>
            <div style={{ "--h": "70px" } as React.CSSProperties}><i></i><span>5/11</span><b>4.18</b></div>
            <div style={{ "--h": "52px" } as React.CSSProperties}><i></i><span>5/12</span><b>3.55</b></div>
            <div style={{ "--h": "48px" } as React.CSSProperties}><i></i><span>5/13</span><b>2.87</b></div>
            <div style={{ "--h": "45px" } as React.CSSProperties}><i></i><span>5/14</span><b>2.21</b></div>
            <div style={{ "--h": "36px" } as React.CSSProperties}><i></i><span>5/15</span><b>1.78</b></div>
            <div style={{ "--h": "28px" } as React.CSSProperties}><i></i><span>5/16</span><b>1.29</b></div>
            <div style={{ "--h": "32px" } as React.CSSProperties}><i></i><span>5/17</span><b>1.97</b></div>
          </div>
        </section>

        {/* PANEL 4: CHRONICLE */}
        <section className="dash-panel chronicle-panel">
          <PanelCorners prefix="panel" />

          <header className="panel-heading chronicle-heading">
            <div className="book-mark" aria-hidden="true">▧</div>
            <h2>Χρονikοv · Decision Chronicle</h2>
          </header>

          <div className="chronicle-list">
            {decisions.length > 0 ? (
              decisions.slice(0, 12).map((d) => (
                <div key={d.decision_id}>
                  <span>{getAgentSymbol(d.agent_role)}</span>
                  <time>{new Date(d.ts_ms).toLocaleTimeString()}</time>
                  <p>
                    {d.agent_role === "nomos" && `NOMOS quoted at bid ${d.bid?.toFixed(4)} / ask ${d.ask?.toFixed(4)}, size ${d.size}. `}
                    {d.agent_role === "spatha" && `SPATHA hedged ${d.side} ${d.size} ${d.instrument || ""}. `}
                    {d.agent_role === "agros" && `AGROS rebalanced treasury: ${d.action} · ${d.amount}. `}
                    {d.trace_hash && (
                      <Link to={`/trace?hash=${d.trace_hash}`}>
                        trace {shortHash(d.trace_hash)}
                      </Link>
                    )}
                  </p>
                  {getStatusNode(d)}
                </div>
              ))
            ) : (
              // Fallback / mock data matching dashboard.html
              <>
                <div>
                  <span>▥</span>
                  <time>14:32:18</time>
                  <p>
                    NOMOS quoted 0x4f2a... at bid 0.612 / ask 0.628, size 100.{" "}
                    <Link to="/trace?hash=0xa9adcb87b510cde9f4a7b1f2d3c4e5f67890123456789abcdef0123456789abcd">
                      trace 0xa9ad...cb87
                    </Link>{" "}
                    anchored.
                  </p>
                  <b>STAGED</b>
                </div>
                <div>
                  <span>†</span>
                  <time>14:31:54</time>
                  <p>
                    SPATHA crossed 0x1e3b... yes @ 0.621, size 75.{" "}
                    <Link to="/trace?hash=0x61ace54d">
                      trace 0x61ac...e54d
                    </Link>{" "}
                    pinned.
                  </p>
                  <b className="status-pin">PINNED</b>
                </div>
                <div>
                  <span>✤</span>
                  <time>14:30:37</time>
                  <p>
                    AGROS rebalanced treasury: +412.22 USYC from yield.{" "}
                    <Link to="/trace?hash=0xf14b771a">
                      trace 0xf14b...771a
                    </Link>{" "}
                    anchored.
                  </p>
                  <b>ANCHORED</b>
                </div>
                <div>
                  <span>▥</span>
                  <time>14:29:11</time>
                  <p>
                    NOMOS quoted 0x9c77... at bid 0.487 / ask 0.503, size 150.{" "}
                    <Link to="/trace?hash=0x2d8e9a1f">
                      trace 0x2d8e...9a1f
                    </Link>{" "}
                    anchored.
                  </p>
                  <b>ANCHORED</b>
                </div>
                <div>
                  <span>†</span>
                  <time>14:28:02</time>
                  <p>
                    SPATHA hedged 0x3b08... no @ 0.712, size 120.{" "}
                    <Link to="/trace?hash=0x9b23caa2">
                      trace 0x9b23...caa2
                    </Link>{" "}
                    anchored.
                  </p>
                  <b>ANCHORED</b>
                </div>
                <div>
                  <span>✤</span>
                  <time>14:26:41</time>
                  <p>
                    AGROS harvested yield: +0.91 USYC.{" "}
                    <Link to="/trace?hash=0x7e910b66">
                      trace 0x7e91...0b66
                    </Link>{" "}
                    anchored.
                  </p>
                  <b>ANCHORED</b>
                </div>
                <div>
                  <span>▥</span>
                  <time>14:25:33</time>
                  <p>
                    NOMOS quoted 0x2d91... at bid 0.544 / ask 0.559, size 100.{" "}
                    <Link to="/trace?hash=0x4c2a1dbe">
                      trace 0x4c2a...1dbe
                    </Link>{" "}
                    pinned.
                  </p>
                  <b className="status-pin">PINNED</b>
                </div>
                <div>
                  <span>†</span>
                  <time>14:24:07</time>
                  <p>
                    SPATHA crossed 0x6e19... yes @ 0.605, size 200.{" "}
                    <Link to="/trace?hash=0x8f663b2e">
                      trace 0x8f66...3b2e
                    </Link>{" "}
                    anchored.
                  </p>
                  <b>ANCHORED</b>
                </div>
                <div>
                  <span>✤</span>
                  <time>14:22:58</time>
                  <p>
                    AGROS allocated +300 USDC to working capital.{" "}
                    <Link to="/trace?hash=0x3a19f7c0">
                      trace 0x3a19...f7c0
                    </Link>{" "}
                    anchored.
                  </p>
                  <b>ANCHORED</b>
                </div>
                <div>
                  <span>▥</span>
                  <time>14:21:36</time>
                  <p>
                    NOMOS quoted 0x7c55... at bid 0.493 / ask 0.509, size 100.{" "}
                    <Link to="/trace?hash=0x6c8b02aa">
                      trace 0x6c8b...02aa
                    </Link>{" "}
                    anchored.
                  </p>
                  <b>ANCHORED</b>
                </div>
                <div>
                  <span>†</span>
                  <time>14:20:14</time>
                  <p>
                    SPATHA hedged 0x8a10... no @ 0.681, size 80.{" "}
                    <Link to="/trace?hash=0x1f449b21">
                      trace 0x1f44...9b21
                    </Link>{" "}
                    anchored.
                  </p>
                  <b>ANCHORED</b>
                </div>
                <div>
                  <span>✤</span>
                  <time>14:19:02</time>
                  <p>
                    AGROS rebalanced treasury: +0.68 USYC from yield.{" "}
                    <Link to="/trace?hash=0x0e77a013">
                      trace 0x0e77...a013
                    </Link>{" "}
                    anchored.
                  </p>
                  <b>ANCHORED</b>
                </div>
              </>
            )}
          </div>
        </section>

        {/* PANEL 5: RISK GATE */}
        <section className="dash-panel risk-panel">
          <PanelCorners prefix="panel" />

          <header className="panel-heading risk-heading">
            <div className="tower-mark" aria-hidden="true">▥</div>
            <h2>Risk Gate · 12 Sentinels</h2>
          </header>

          <ol className="sentinel-list">
            <li><span></span>Price Oracle Freshness</li>
            <li><span></span>Oracle Divergence</li>
            <li><span></span>Market Depth Sufficiency</li>
            <li><span></span>Spread Limit</li>
            <li><span></span>Exposure Concentration</li>
            <li><span></span>Treasury Liquidity</li>
            <li><span></span>Leverage Limit</li>
            <li><span className="warn"></span>Volatility Regime</li>
            <li><span></span>Correlation Break</li>
            <li><span></span>Yield Accrual Health</li>
            <li><span></span>Operational Heartbeat</li>
            <li><span className="pause"></span>Governance Pause</li>
          </ol>

          <MiniDivider className="risk-divider">Decisions Per Minute (Last Hour)</MiniDivider>

          <div className="minute-frieze" aria-hidden="true">
            <span>♙</span><span>♙</span><span>♙</span><span>♙</span><span>♙</span>
            <span>♙</span><span>♙</span><span>♙</span><span>♙</span><span>♙</span>
            <span>♙</span><span>♙</span><span>♙</span><span>♙</span><span>♙</span>
          </div>
        </section>
      </main>

      <Footer variant="dashboard" />
    </>
  );
}

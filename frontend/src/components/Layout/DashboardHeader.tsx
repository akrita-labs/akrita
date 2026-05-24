import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import type { WsStatus } from "../../hooks/useLiveSocket";

interface DashboardHeaderProps {
  wsStatus: WsStatus;
}

export default function DashboardHeader({ wsStatus }: DashboardHeaderProps) {
  const [blockNumber, setBlockNumber] = useState(1847293);

  // Increment the block number occasionally to make the UI feel alive
  useEffect(() => {
    const interval = setInterval(() => {
      setBlockNumber((prev) => prev + Math.floor(Math.random() * 2));
    }, 12000);
    return () => clearInterval(interval);
  }, []);

  const formatBlock = (num: number) => {
    return "#" + num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  };

  const statusText = wsStatus === "live" ? "LIVE" : wsStatus === "connecting" ? "CONNECTING" : "OFFLINE";
  
  // Choose class for the live pill based on WS status
  const wsClass = wsStatus === "live" 
    ? "status-connected" 
    : wsStatus === "connecting" 
    ? "status-pending" 
    : "status-disconnected";

  return (
    <header className="dashboard-header">
      <Link className="dashboard-brand" to="/" aria-label="AKRITA home">
        <span className="dashboard-brand-name">AKRITA</span>
        <span className="dashboard-brand-sub">AKRITAI</span>
      </Link>

      <div className="dashboard-network">
        <span className="network-cross" aria-hidden="true">✠</span>
        <span>Arc testnet · block <b id="arc-block">{formatBlock(blockNumber)}</b></span>
      </div>

      <div className="dashboard-live">
        <span className={`live-pill ${wsClass}`} style={{ 
          borderColor: wsStatus === "live" ? "var(--dash-green)" : wsStatus === "connecting" ? "var(--dash-gold)" : "var(--dash-red)",
          color: wsStatus === "live" ? "var(--dash-green)" : wsStatus === "connecting" ? "var(--dash-gold)" : "var(--dash-red)"
        }}>
          {statusText} <b aria-hidden="true" className={wsClass} style={{
            color: wsStatus === "live" ? "var(--dash-green)" : wsStatus === "connecting" ? "var(--dash-gold)" : "var(--dash-red)"
          }}>✠</b>
        </span>
        <span className="live-flower" aria-hidden="true">✾</span>
      </div>
    </header>
  );
}

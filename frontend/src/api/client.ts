// AKRITA API client — matches original app.js logic and proxy configuration.

export const API_BASE = window.location.origin;

// WS URL mapping http -> ws
export const WS_URL = API_BASE.replace(/^http/, "ws") + "/live";

// Types matching the backend schema
export interface BalanceDetails {
  USYC?: number;
  USDC?: number;
  [token: string]: number | undefined;
}

export interface WalletBalances {
  arc?: BalanceDetails;
  [chain: string]: BalanceDetails | undefined;
}

export interface BalancesResponse {
  "agros-keeper"?: WalletBalances;
  usyc_nav?: number;
  usyc_apy?: number;
  [walletAddress: string]: WalletBalances | number | undefined; // to handle usyc_nav, usyc_apy
}

export interface Fill {
  side: "BUY" | "SELL";
  market_id: string;
  size: number;
  price: number;
  builder_fee_usdc?: number;
  tx_hash?: string;
  ts_ms?: number;
}

export interface FillsResponse {
  fills: Fill[];
  cumulative_builder_fees_usdc: number;
}

export interface Decision {
  decision_id: number;
  agent_role: "nomos" | "spatha" | "agros";
  ts_ms: number;
  trace_hash?: string;
  ipfs_cid?: string;
  arc_tx_hash?: string;
  // Nomos specific fields
  bid?: number;
  ask?: number;
  size?: number;
  // Spatha specific fields
  side?: string;
  instrument?: string;
  // Agros specific fields
  action?: string;
  amount?: string;
}

export interface DecisionsResponse {
  decisions: Decision[];
}

export async function fetchBalances(): Promise<BalancesResponse> {
  const res = await fetch(`${API_BASE}/state/balances`);
  if (!res.ok) throw new Error("Failed to fetch balances");
  return res.json();
}

export async function fetchFills(limit = 50): Promise<FillsResponse> {
  const res = await fetch(`${API_BASE}/state/fills?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch fills");
  return res.json();
}

export async function fetchDecisions(limit = 50): Promise<DecisionsResponse> {
  const res = await fetch(`${API_BASE}/state/decisions?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch decisions");
  return res.json();
}

export async function fetchTreasury(limit = 20): Promise<unknown> {
  const res = await fetch(`${API_BASE}/state/treasury?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch treasury");
  return res.json();
}

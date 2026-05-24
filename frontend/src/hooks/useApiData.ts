import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchBalances,
  fetchFills,
  fetchDecisions,
} from "../api/client";
import type {
  BalancesResponse,
  FillsResponse,
  Decision,
} from "../api/client";

export function useApiData() {
  const [balances, setBalances] = useState<BalancesResponse | null>(null);
  const [fillsData, setFillsData] = useState<FillsResponse | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Keep a ref of the hydrate function to prevent recreation while keeping it callable
  const activeFetchPromiseRef = useRef<Promise<void> | null>(null);

  const hydrate = useCallback(async () => {
    // If there's an ongoing request, return it
    if (activeFetchPromiseRef.current) {
      return activeFetchPromiseRef.current;
    }

    const fetchPromise = (async () => {
      try {
        const [balR, fillsR, decisionsR] = await Promise.all([
          fetchBalances(),
          fetchFills(50),
          fetchDecisions(50),
        ]);

        setBalances(balR);
        setFillsData(fillsR);
        setDecisions(decisionsR.decisions || []);
        setError(null);
      } catch (err) {
        console.error("Hydration failed:", err);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
        activeFetchPromiseRef.current = null;
      }
    })();

    activeFetchPromiseRef.current = fetchPromise;
    return fetchPromise;
  }, []);

  useEffect(() => {
    // Initial fetch
    hydrate();

    // Safety net: periodic background refresh every 8 seconds
    const interval = setInterval(() => {
      hydrate();
    }, 8000);

    return () => clearInterval(interval);
  }, [hydrate]);

  return {
    balances,
    fillsData,
    decisions,
    loading,
    error,
    hydrate,
  };
}

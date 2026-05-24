import { useEffect, useState, useRef } from "react";
import { WS_URL } from "../api/client";

export type WsStatus = "connecting" | "live" | "disconnected";

export function useLiveSocket(onEvent: (evt: { type: string; [key: string]: unknown }) => void) {
  const [status, setStatus] = useState<WsStatus>("disconnected");
  const onEventRef = useRef(onEvent);

  // Keep event handler ref fresh to avoid stale closures
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    let isMounted = true;

    function connect() {
      if (!isMounted) return;
      
      setStatus("connecting");
      try {
        ws = new WebSocket(WS_URL);
      } catch (err) {
        console.warn("WebSocket connection attempt failed:", err);
        setStatus("disconnected");
        reconnectTimeout = setTimeout(connect, 2000);
        return;
      }

      ws.onopen = () => {
        if (!isMounted) return;
        setStatus("live");
      };

      ws.onmessage = (msg) => {
        if (!isMounted) return;
        try {
          const data = JSON.parse(msg.data);
          onEventRef.current(data);
        } catch (e) {
          console.warn("bad event received via WebSocket:", e);
        }
      };

      ws.onclose = () => {
        if (!isMounted) return;
        setStatus("disconnected");
        reconnectTimeout = setTimeout(connect, 2000);
      };

      ws.onerror = () => {
        // ws.close() is automatically called on error, triggering the onclose handler
      };
    }

    connect();

    return () => {
      isMounted = false;
      if (ws) {
        ws.close();
      }
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
      }
    };
  }, []);

  return status;
}

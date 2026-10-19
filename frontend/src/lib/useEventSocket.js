import { useEffect, useRef, useState, useCallback } from "react";

/**
 * Connects to /ws/{code}. Keeps the latest full `state` snapshot and forwards every
 * other message to onMessage. Reconnects with backoff; the server re-sends state on connect.
 */
export function useEventSocket(code, { token = null, onMessage, onAuthError } = {}) {
  const [state, setState] = useState(null);
  const [connected, setConnected] = useState(false);
  const [offset, setOffset] = useState(0); // serverTime - clientTime, in ms
  const handlers = useRef({ onMessage, onAuthError });
  handlers.current = { onMessage, onAuthError };

  useEffect(() => {
    if (!code) return undefined;
    let ws;
    let closed = false;
    let retry = 0;
    let pingTimer;
    let retryTimer;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const qs = token ? `?token=${encodeURIComponent(token)}` : "";
      ws = new WebSocket(`${proto}://${window.location.host}/ws/${encodeURIComponent(code)}${qs}`);
      ws.onopen = () => {
        retry = 0;
        setConnected(true);
        pingTimer = setInterval(() => ws.readyState === 1 && ws.send("ping"), 25000);
      };
      ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === "state") {
          setOffset(msg.data.server_time * 1000 - Date.now());
          setState(msg.data);
        } else if (msg.type !== "pong") {
          handlers.current.onMessage?.(msg);
        }
      };
      ws.onclose = (ev) => {
        setConnected(false);
        clearInterval(pingTimer);
        if (closed) return;
        if ([4401, 4403, 4404].includes(ev.code)) {
          handlers.current.onAuthError?.(ev.code);
          return;
        }
        retry = Math.min(retry + 1, 6);
        retryTimer = setTimeout(connect, 500 * 2 ** retry);
      };
    };
    connect();
    return () => {
      closed = true;
      clearInterval(pingTimer);
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, [code, token]);

  const serverNow = useCallback(() => Date.now() + offset, [offset]);
  return { state, connected, serverNow };
}

/** Seconds remaining until a server-side deadline (epoch seconds), ticking every 250 ms. */
export function useCountdown(deadline, serverNow, frozenRemaining = null) {
  const [now, setNow] = useState(() => serverNow());
  useEffect(() => {
    if (!deadline) return undefined;
    const t = setInterval(() => setNow(serverNow()), 250);
    return () => clearInterval(t);
  }, [deadline, serverNow]);
  if (!deadline) return frozenRemaining;
  return Math.max(0, deadline - now / 1000);
}

"use client";

import { useAuth0 } from "@auth0/auth0-react";
import { useEffect, useRef, useState } from "react";

import type { WSClientMessage, WSServerMessage } from "@/lib/types";

/**
 * Hook that manages a WebSocket connection to /ws on the same origin.
 *
 * Flow:
 *  1. Hook mounts -> fetch JWT via Auth0 (silent)
 *  2. Open WS to wss://{host}/api/ws
 *  3. Send {type:"auth", token} as first frame
 *  4. Wait for {type:"auth.ok"}; mark connected
 *  5. Caller can now sendMessage() and supply onMessage handler
 *
 * Automatic reconnect with exponential backoff (max 30s) if the connection
 * drops unexpectedly. The hook re-authenticates and re-subscribes on each
 * reconnect — that logic is the caller's job via onConnected().
 */

interface UseWebSocketOptions {
  onMessage?: (msg: WSServerMessage) => void;
  onConnected?: () => void;
  onDisconnected?: () => void;
  /** Skip connecting entirely (useful when waiting on auth) */
  enabled?: boolean;
}

interface UseWebSocketReturn {
  isConnected: boolean;
  isAuthenticated: boolean;
  sendMessage: (msg: WSClientMessage) => void;
  lastError: string | null;
}

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

function wsUrl(): string {
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api/ws`;
}

export function useWebSocket({
  onMessage,
  onConnected,
  onDisconnected,
  enabled = true,
}: UseWebSocketOptions): UseWebSocketReturn {
  const { getAccessTokenSilently } = useAuth0();
  const [isConnected, setIsConnected] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stopRef = useRef(false);

  // Keep latest callbacks in refs so we don't have to reconnect when they
  // change between renders.
  const onMessageRef = useRef(onMessage);
  const onConnectedRef = useRef(onConnected);
  const onDisconnectedRef = useRef(onDisconnected);
  useEffect(() => {
    onMessageRef.current = onMessage;
    onConnectedRef.current = onConnected;
    onDisconnectedRef.current = onDisconnected;
  }, [onMessage, onConnected, onDisconnected]);

  useEffect(() => {
    if (!enabled) return;
    stopRef.current = false;

    async function connect() {
      if (stopRef.current) return;

      let token: string;
      try {
        token = await getAccessTokenSilently({
          authorizationParams: {
            audience: process.env.NEXT_PUBLIC_AUTH0_AUDIENCE,
          },
        });
      } catch (e) {
        setLastError(`auth failed: ${(e as Error).message}`);
        scheduleReconnect();
        return;
      }

      const url = wsUrl();
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.addEventListener("open", () => {
        // Send auth as first message
        ws.send(JSON.stringify({ type: "auth", token } satisfies WSClientMessage));
      });

      ws.addEventListener("message", (event) => {
        let msg: WSServerMessage;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }

        if (msg.type === "auth.ok") {
          setIsConnected(true);
          setIsAuthenticated(true);
          setLastError(null);
          reconnectAttemptRef.current = 0;
          onConnectedRef.current?.();
          return;
        }

        if (msg.type === "error") {
          setLastError(msg.message);
        }

        onMessageRef.current?.(msg);
      });

      ws.addEventListener("close", () => {
        wsRef.current = null;
        setIsConnected(false);
        setIsAuthenticated(false);
        onDisconnectedRef.current?.();
        if (!stopRef.current) {
          scheduleReconnect();
        }
      });

      ws.addEventListener("error", () => {
        // The close handler will run too; don't double-handle reconnect here.
        setLastError("WebSocket error");
      });
    }

    function scheduleReconnect() {
      if (stopRef.current) return;
      const attempt = reconnectAttemptRef.current++;
      const delay = Math.min(
        RECONNECT_BASE_MS * Math.pow(2, attempt),
        RECONNECT_MAX_MS,
      );
      reconnectTimeoutRef.current = setTimeout(connect, delay);
    }

    connect();

    return () => {
      stopRef.current = true;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close(1000, "component unmounting");
      }
      wsRef.current = null;
      setIsConnected(false);
      setIsAuthenticated(false);
    };
  }, [enabled, getAccessTokenSilently]);

  function sendMessage(msg: WSClientMessage) {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }

  return { isConnected, isAuthenticated, sendMessage, lastError };
}

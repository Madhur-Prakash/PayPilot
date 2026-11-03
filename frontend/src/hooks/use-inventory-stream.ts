"use client";

/**
 * The live inventory socket.
 *
 * Realtime is a *notification* channel, not a source of truth. The socket says
 * "this changed"; React Query still owns the data. So every frame invalidates the
 * relevant query rather than patching a local cache, and a reconnect refetches
 * the authoritative snapshot instead of trying to replay what was missed.
 *
 * Reconnection backs off rather than hammering a backend that is restarting.
 */

import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { toast } from "sonner";

import { ensureFreshAccessToken, getAccessToken } from "@/lib/api/client";
import { API_BASE_URL } from "@/lib/constants/config";

export type InventoryEvent =
  | "connected"
  | "inventory.updated"
  | "inventory.low_stock"
  | "inventory.reorder_started"
  | "inventory.purchase_order_updated"
  | "inventory.purchase_received"
  | "inventory.workflow_completed"
  | "inventory.aging"
  | "inventory.reconciled";

export interface InventoryFrame {
  event: InventoryEvent | string;
  merchant_id: string;
  at: string;
  payload: Record<string, unknown>;
}

export type StreamStatus = "connecting" | "live" | "offline";

/** 1s, 2s, 4s… capped. Long enough to let a restart finish, short enough to feel live. */
const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];

function socketUrl(token: string): string {
  // One source of truth for the API origin; re-deriving it here is how the two
  // copies drifted apart in the first place.
  const url = new URL(`${API_BASE_URL}/inventory/stream`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  // A browser cannot set headers on a websocket, so the token rides in the query
  // string. The backend verifies it before accepting the connection.
  url.searchParams.set("token", token);
  return url.toString();
}

export function useInventoryStream(options?: {
  onEvent?: (frame: InventoryFrame) => void;
  notify?: boolean;
}) {
  const queryClient = useQueryClient();
  const [status, setStatus] = React.useState<StreamStatus>("connecting");
  const [lastEvent, setLastEvent] = React.useState<InventoryFrame | null>(null);

  const socketRef = React.useRef<WebSocket | null>(null);
  const attemptRef = React.useRef(0);
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef = React.useRef(false);
  const onEventRef = React.useRef(options?.onEvent);
  onEventRef.current = options?.onEvent;
  const notify = options?.notify ?? true;

  React.useEffect(() => {
    closedRef.current = false;

    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ["inventory"] });
      void queryClient.invalidateQueries({ queryKey: ["purchase-orders"] });
      void queryClient.invalidateQueries({ queryKey: ["inventory-automation"] });
    };

    const connect = () => {
      const token = getAccessToken();
      if (!token) {
        // Mid-refresh, or signed out. Back off and look again rather than
        // stopping for good - the backoff caps at 15s, and this self-heals.
        scheduleReconnect();
        return;
      }

      // The handshake is rejected before `onopen` when the token is stale, so
      // this distinguishes "auth failed" from "the connection dropped".
      let opened = false;
      let socket: WebSocket;
      try {
        socket = new WebSocket(socketUrl(token));
      } catch {
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;
      setStatus("connecting");

      socket.onopen = () => {
        opened = true;
        attemptRef.current = 0;
        setStatus("live");
        // The snapshot may have moved while we were away; trust the API, not a replay.
        refresh();
      };

      socket.onmessage = (raw) => {
        let frame: InventoryFrame;
        try {
          frame = JSON.parse(raw.data as string) as InventoryFrame;
        } catch {
          return;
        }
        if (frame.event === "connected") return;

        setLastEvent(frame);
        onEventRef.current?.(frame);
        refresh();

        if (notify) {
          if (frame.event === "inventory.low_stock") {
            toast.warning("Low stock", {
              description: String(frame.payload.sku ?? "An item crossed its reorder point."),
            });
          } else if (frame.event === "inventory.purchase_order_updated") {
            toast.success(`Purchase order ${String(frame.payload.reference ?? "")}`, {
              description: String(frame.payload.status ?? ""),
            });
          }
        }
      };

      socket.onclose = () => {
        socketRef.current = null;
        if (closedRef.current) return;
        if (opened) {
          scheduleReconnect();
          return;
        }
        // Closed without ever opening: the server rejected the handshake, and
        // by far the likeliest reason is an expired access token. No 401 ever
        // reaches the Axios interceptor here, so renew the token ourselves --
        // otherwise every retry presents the same dead one and the socket never
        // comes back.
        void ensureFreshAccessToken().finally(scheduleReconnect);
      };
      socket.onerror = () => socket.close();
    };

    const scheduleReconnect = () => {
      if (closedRef.current) return;
      setStatus("offline");
      const delay = BACKOFF_MS[Math.min(attemptRef.current, BACKOFF_MS.length - 1)];
      attemptRef.current += 1;
      timerRef.current = setTimeout(connect, delay);
    };

    connect();

    return () => {
      closedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [queryClient, notify]);

  return { status, lastEvent };
}

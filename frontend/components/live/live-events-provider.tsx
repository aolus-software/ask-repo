"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { endpoints } from "@/lib/api/endpoints";
import { parseSseStream } from "@/lib/ask/sse";
import { nextDelay } from "@/lib/live/backoff";
import { ALL_LIVE_KEYS, type InvalidatePayload, keysToInvalidate } from "@/lib/live/invalidation";
import { LiveEventsContext } from "@/hooks/use-live-events";

/**
 * One live-update stream per tab (issue #48). Events are hints: each becomes a React
 * Query invalidation, and the REST refetch shows the change. While `connected` is false the
 * hooks poll exactly as they did before this provider existed.
 *
 * `fetch` rather than `EventSource`, so the BFF's refresh-on-401 applies and the backoff is
 * ours. The stream closes while the tab is hidden and reopens — with a full refetch on
 * `ready` — when it is visible again.
 */
export function LiveEventsProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let stopped = false;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    function invalidateAll() {
      for (const queryKey of ALL_LIVE_KEYS) void queryClient.invalidateQueries({ queryKey });
    }

    function schedule() {
      if (stopped || document.visibilityState === "hidden") return;
      timer = setTimeout(() => void connect(), nextDelay(attempt));
      attempt += 1;
    }

    async function connect() {
      if (stopped || document.visibilityState === "hidden") return;
      controller = new AbortController();
      try {
        const response = await fetch(`/api${endpoints.events}`, {
          signal: controller.signal,
          cache: "no-store",
          headers: { accept: "text/event-stream" },
        });
        // An unrefreshable session: stop, and let the normal session handling redirect.
        if (response.status === 401) return;
        if (!response.ok || !response.body) {
          schedule();
          return;
        }
        for await (const event of parseSseStream(response.body, controller.signal)) {
          if (event.event === "ready") {
            attempt = 0;
            setConnected(true);
            invalidateAll();
          } else if (event.event === "resync") {
            invalidateAll();
          } else if (event.event === "invalidate") {
            for (const queryKey of keysToInvalidate(event.data as InvalidatePayload)) {
              void queryClient.invalidateQueries({ queryKey });
            }
          }
        }
      } catch {
        // Aborted or dropped — fall through to reconnect.
      }
      setConnected(false);
      schedule();
    }

    function disconnect() {
      if (timer) clearTimeout(timer);
      timer = null;
      controller?.abort();
      controller = null;
      setConnected(false);
    }

    function onVisibilityChange() {
      if (document.visibilityState === "hidden") {
        disconnect();
      } else if (!controller) {
        attempt = 0;
        void connect();
      }
    }

    void connect();
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onVisibilityChange);
      disconnect();
    };
  }, [queryClient]);

  return <LiveEventsContext.Provider value={{ connected }}>{children}</LiveEventsContext.Provider>;
}

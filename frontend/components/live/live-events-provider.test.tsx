import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveEventsProvider } from "@/components/live/live-events-provider";
import { useLiveEvents } from "@/hooks/use-live-events";
import { keys } from "@/lib/query/keys";

function sseBody(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame));
      // Left open: a live stream does not end on its own.
    },
  });
}

function Probe() {
  const { connected } = useLiveEvents();
  return <p>{connected ? "connected" : "polling"}</p>;
}

function renderProvider(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <LiveEventsProvider>
        <Probe />
      </LiveEventsProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("LiveEventsProvider", () => {
  it("connects on ready and invalidates on an event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            sseBody([
              "event: ready\ndata: {}\n\n",
              'event: invalidate\ndata: {"kind":"checklist_module","id":"m1","projectId":"p1"}\n\n',
            ]),
            { status: 200, headers: { "content-type": "text/event-stream" } },
          ),
      ),
    );
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");

    renderProvider(client);

    expect(await screen.findByText("connected")).toBeInTheDocument();
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        queryKey: keys.checklistModules.detail("m1"),
      }),
    );
  });

  it("stays on polling when the stream is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          { detail: { code: "LIVE_EVENTS_UNAVAILABLE", message: "poll" } },
          { status: 503 },
        ),
      ),
    );

    renderProvider(new QueryClient());

    expect(await screen.findByText("polling")).toBeInTheDocument();
  });

  it("stops reconnecting for good after a 401, even across a visibility change", async () => {
    const spy = vi.fn(async () => Response.json({}, { status: 401 }));
    vi.stubGlobal("fetch", spy);
    const originalDescriptor = Object.getOwnPropertyDescriptor(
      document,
      "visibilityState",
    );

    try {
      renderProvider(new QueryClient());
      await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => "hidden",
      });
      document.dispatchEvent(new Event("visibilitychange"));

      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => "visible",
      });
      document.dispatchEvent(new Event("visibilitychange"));

      // Give any (incorrect) reconnect a chance to fire before asserting it didn't.
      await new Promise((resolve) => setTimeout(resolve, 10));
      expect(spy).toHaveBeenCalledTimes(1);
    } finally {
      if (originalDescriptor) {
        Object.defineProperty(document, "visibilityState", originalDescriptor);
      }
    }
  });

  it("invalidates eval queries on a resync", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            sseBody(["event: ready\ndata: {}\n\n", "event: resync\ndata: {}\n\n"]),
            { status: 200, headers: { "content-type": "text/event-stream" } },
          ),
      ),
    );
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");

    renderProvider(client);

    expect(await screen.findByText("connected")).toBeInTheDocument();
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        queryKey: keys.eval.all,
      }),
    );
  });
});

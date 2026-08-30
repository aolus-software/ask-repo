import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type AskState,
  initialAskState,
  reduceAskEvent,
  useAskStream,
} from "@/hooks/use-ask-stream";

import { keys } from "@/lib/query/keys";

const apiFetchRaw = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiFetchRaw }));

function run(frames: { event: string; data: unknown }[]): AskState {
  return frames.reduce(reduceAskEvent, initialAskState());
}

describe("reduceAskEvent", () => {
  it("records the phase from a status event", () => {
    expect(run([{ event: "status", data: { phase: "retrieving" } }]).phase).toBe(
      "retrieving",
    );
  });

  it("accepts citations before the first token", () => {
    const state = run([
      {
        event: "citations",
        data: { citations: [{ index: 1, filePath: "app/fees.py" }] },
      },
      { event: "token", data: { text: "The" } },
    ]);
    expect(state.citations).toHaveLength(1);
    expect(state.text).toBe("The");
  });

  it("accumulates tokens in order", () => {
    const state = run([
      { event: "token", data: { text: "Hello" } },
      { event: "token", data: { text: ", " } },
      { event: "token", data: { text: "world" } },
    ]);
    expect(state.text).toBe("Hello, world");
  });

  it("carries groundingWarnings through to the UI state", () => {
    const state = run([
      {
        event: "done",
        data: {
          messageId: "m1",
          model: "qwen",
          finishReason: "stop",
          citedIndexes: [1],
          groundingWarnings: ["unknown_paths"],
        },
      },
    ]);
    expect(state.groundingWarnings).toEqual(["unknown_paths"]);
    expect(state.citedIndexes).toEqual([1]);
    expect(state.terminal).toBe("done");
    expect(state.finishReason).toBe("stop");
  });

  it("records an error terminator with its finishReason", () => {
    const state = run([
      {
        event: "error",
        data: {
          messageId: "m1",
          code: "LLM_UNAVAILABLE",
          message: "The model is unavailable.",
          finishReason: "error",
        },
      },
    ]);
    expect(state.terminal).toBe("error");
    expect(state.finishReason).toBe("error");
    expect(state.errorMessage).toBe("The model is unavailable.");
  });

  it("ignores an unknown event", () => {
    const state = run([
      { event: "reasoning", data: { step: "critique" } },
      { event: "token", data: { text: "hi" } },
    ]);
    expect(state.text).toBe("hi");
    expect(state.terminal).toBeNull();
  });

  it("leaves terminal null when the stream carried no terminator", () => {
    // The caller marks this `interrupted` — the third termination the SSE contract
    // does not name (design spec §9.5).
    expect(run([{ event: "token", data: { text: "partial" } }]).terminal).toBeNull();
  });
});

function openSseResponse(): {
  response: Response;
  push: (frame: string) => void;
  close: () => void;
} {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: { body } as Response,
    push: (frame: string) => controller.enqueue(encoder.encode(frame)),
    close: () => controller.close(),
  };
}

function sseResponse(frames: string[]): Response {
  const encoder = new TextEncoder();
  return {
    body: new ReadableStream({
      start(controller) {
        for (const frame of frames) controller.enqueue(encoder.encode(frame));
        controller.close();
      },
    }),
  } as Response;
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return createElement(QueryClientProvider, { client }, children);
}

describe("useAskStream reconciliation", () => {
  afterEach(() => vi.clearAllMocks());

  it("marks the answer reconciled once the stored message has been refetched", async () => {
    // The screen renders `state.text` AND the message list. Both hold the same answer
    // after the refetch, so one of them has to stop — `reconciled` is that signal, and
    // without it the answer renders twice until the page is reloaded.
    apiFetchRaw.mockResolvedValue(
      sseResponse([
        'event: token\ndata: {"text":"hello"}\n\n',
        'event: done\ndata: {"messageId":"m1","model":"qwen","finishReason":"stop","citedIndexes":[],"groundingWarnings":[]}\n\n',
      ]),
    );

    const { result } = renderHook(() => useAskStream("c1"), { wrapper });

    await result.current.ask("why?");

    await waitFor(() => {
      expect(result.current.state?.terminal).toBe("done");
      expect(result.current.state?.reconciled).toBe(true);
    });
    expect(result.current.state?.text).toBe("hello");
  });

  it("reconciles an interrupted stream too", async () => {
    // No terminator at all. The backend still persisted the partial, so the stored
    // row still arrives and the streamed copy still has to stand down.
    apiFetchRaw.mockResolvedValue(
      sseResponse(['event: token\ndata: {"text":"partial"}\n\n']),
    );

    const { result } = renderHook(() => useAskStream("c1"), { wrapper });

    await result.current.ask("why?");

    await waitFor(() => {
      expect(result.current.state?.terminal).toBe("interrupted");
      expect(result.current.state?.reconciled).toBe(true);
    });
  });

  it("does not reconcile until the stored message has actually landed", async () => {
    // The load-bearing detail is that the invalidation is AWAITED. Fired and
    // forgotten, `reconciled` would flip the instant the stream ended — before the
    // message list had the answer — and the answer would blink out and back in.
    apiFetchRaw.mockResolvedValue(
      sseResponse([
        'event: token\ndata: {"text":"hello"}\n\n',
        'event: done\ndata: {"messageId":"m1","model":"qwen","finishReason":"stop","citedIndexes":[],"groundingWarnings":[]}\n\n',
      ]),
    );

    let releaseRefetch: () => void = () => {};
    let call = 0;
    const detailFn = vi.fn(() => {
      call += 1;
      // First call is the mount; the second is the post-stream refetch, held open.
      if (call === 1) return Promise.resolve({ id: "c1", messages: [] });
      return new Promise((resolve) => {
        releaseRefetch = () => resolve({ id: "c1", messages: [{ id: "m1" }] });
      });
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(
      () => {
        // An ACTIVE observer on the same key: invalidateQueries only awaits queries
        // something is actually watching, which on the real screen is useConversation.
        useQuery({ queryKey: keys.conversations.detail("c1"), queryFn: detailFn });
        return useAskStream("c1");
      },
      {
        wrapper: ({ children }: { children: React.ReactNode }) =>
          createElement(QueryClientProvider, { client }, children),
      },
    );

    const pending = result.current.ask("why?");

    // The stream is over, but the stored row has not arrived — so the streamed copy
    // is still the only one, and still has to render.
    await waitFor(() => expect(result.current.state?.terminal).toBe("done"));
    expect(result.current.state?.reconciled).toBe(false);

    releaseRefetch();
    await pending;

    await waitFor(() => expect(result.current.state?.reconciled).toBe(true));
  });

  it("refetches the conversation while the answer is still streaming", async () => {
    // The user's message is persisted by the pre-flight, so the server has it before
    // the first byte. Without a refetch here the composer has cleared, the stored row
    // has not been fetched, and the question is on screen nowhere until the answer
    // finishes — which reads as pressing Enter having thrown it away.
    //
    // The assertion is deliberately "during", not "at least twice": a refetch that
    // only happens at the reconciliation point is the bug, and it would satisfy a
    // call-count check.
    const stream = openSseResponse();
    apiFetchRaw.mockResolvedValue(stream.response);

    const detailFn = vi.fn(() => Promise.resolve({ id: "c1", messages: [] }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(
      () => {
        useQuery({ queryKey: keys.conversations.detail("c1"), queryFn: detailFn });
        return useAskStream("c1");
      },
      {
        wrapper: ({ children }: { children: React.ReactNode }) =>
          createElement(QueryClientProvider, { client }, children),
      },
    );

    await waitFor(() => expect(detailFn).toHaveBeenCalled()); // the mount fetch
    detailFn.mockClear();

    const pending = result.current.ask("why is the lease needed?");
    stream.push('event: token\ndata: {"text":"because"}\n\n');

    await waitFor(() => {
      expect(result.current.state?.isStreaming).toBe(true);
      expect(detailFn).toHaveBeenCalled();
    });

    stream.push(
      'event: done\ndata: {"messageId":"m1","model":"qwen","finishReason":"stop","citedIndexes":[],"groundingWarnings":[]}\n\n',
    );
    stream.close();
    await pending;
  });

  it("does not reconcile a pre-flight failure — nothing was streamed", async () => {
    apiFetchRaw.mockRejectedValue(new Error("PROJECT_NOT_READY"));

    const { result } = renderHook(() => useAskStream("c1"), { wrapper });

    await expect(result.current.ask("why?")).rejects.toThrow("PROJECT_NOT_READY");
    expect(result.current.state).toBeNull();
  });
});

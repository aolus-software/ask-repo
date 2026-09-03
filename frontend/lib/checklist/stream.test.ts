import { describe, expect, it, vi } from "vitest";

import { consumeChecklistStream } from "@/lib/checklist/stream";

function streamOf(frames: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const frame of frames) controller.enqueue(encoder.encode(frame));
      controller.close();
    },
  });
  return new Response(body, { headers: { "content-type": "text/event-stream" } });
}

describe("consumeChecklistStream", () => {
  it("delivers citations before the first token, on every route", async () => {
    /** A client must not need to know which route it got in order to parse the
     * stream, so `citations` is emitted exactly once even when it is empty. */
    const order: string[] = [];

    await consumeChecklistStream(
      streamOf([
        'event: citations\ndata: {"citations":[]}\n\n',
        'event: token\ndata: {"text":"hi"}\n\n',
        'event: done\ndata: {"messageId":"m","model":"x","finishReason":"stop","citedIndexes":[],"groundingWarnings":[],"intent":"codebase_question","retrievalAttempts":1}\n\n',
      ]),
      {
        onCitations: () => order.push("citations"),
        onToken: () => order.push("token"),
        onChangeSet: () => order.push("changeSet"),
      },
    );

    expect(order).toEqual(["citations", "token"]);
  });

  it("returns the change set when one arrives after the last token", async () => {
    const onChangeSet = vi.fn();

    const result = await consumeChecklistStream(
      streamOf([
        'event: citations\ndata: {"citations":[]}\n\n',
        'event: token\ndata: {"text":"Add one."}\n\n',
        'event: changeSet\ndata: {"changeSetId":"cs1","summary":"1 added","operations":[{"op":"add","id":"o1","rationale":"r"}]}\n\n',
        'event: done\ndata: {"messageId":"m","model":"x","finishReason":"stop","citedIndexes":[],"groundingWarnings":[],"intent":"codebase_question","retrievalAttempts":1}\n\n',
      ]),
      { onCitations: vi.fn(), onToken: vi.fn(), onChangeSet },
    );

    expect(onChangeSet).toHaveBeenCalledOnce();
    expect(result.changeSet?.changeSetId).toBe("cs1");
    expect(result.content).toBe("Add one.");
    expect(result.done?.finishReason).toBe("stop");
  });

  it("survives a turn that proposes nothing", async () => {
    /** "Why does this expect 410?" is a legitimate turn that changes nothing. */
    const result = await consumeChecklistStream(
      streamOf([
        'event: citations\ndata: {"citations":[]}\n\n',
        'event: token\ndata: {"text":"Because the route is gone."}\n\n',
        'event: done\ndata: {"messageId":"m","model":"x","finishReason":"stop","citedIndexes":[],"groundingWarnings":[],"intent":"codebase_question","retrievalAttempts":1}\n\n',
      ]),
      { onCitations: vi.fn(), onToken: vi.fn(), onChangeSet: vi.fn() },
    );

    expect(result.changeSet).toBeNull();
    expect(result.error).toBeNull();
  });

  it("ignores an event name it does not know", async () => {
    /** An unknown event is ignored, never fatal: the backend adds events over time. */
    const result = await consumeChecklistStream(
      streamOf([
        'event: status\ndata: {"phase":"retrieving"}\n\n',
        'event: somethingNew\ndata: {"x":1}\n\n',
        'event: done\ndata: {"messageId":"m","model":"x","finishReason":"stop","citedIndexes":[],"groundingWarnings":[],"intent":"codebase_question","retrievalAttempts":1}\n\n',
      ]),
      { onCitations: vi.fn(), onToken: vi.fn(), onChangeSet: vi.fn() },
    );

    expect(result.done).not.toBeNull();
  });
});

// Mirrors lib/checklist/stream.test.ts's assertions, for the mockDataChangeSet event.
import { describe, expect, it } from "vitest";

import { consumeMockDataStream } from "@/lib/mock-data/stream";

function sseResponse(body: string): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(body));
        controller.close();
      },
    }),
  );
}

describe("consumeMockDataStream", () => {
  it("collects tokens and the terminal done event", async () => {
    const response = sseResponse(
      'event: citations\ndata: {"citations":[]}\n\n' +
        'event: token\ndata: {"text":"Here"}\n\n' +
        'event: token\ndata: {"text":" you go"}\n\n' +
        'event: done\ndata: {"messageId":"m1","model":"x","finishReason":"stop","citedIndexes":[],"groundingWarnings":[],"intent":"codebase_question","retrievalAttempts":0}\n\n',
    );
    const result = await consumeMockDataStream(response, {
      onCitations: () => {},
      onToken: () => {},
      onChangeSet: () => {},
    });
    expect(result.content).toBe("Here you go");
    expect(result.done?.finishReason).toBe("stop");
    // A turn that proposes nothing is legitimate, not an error -- the change set
    // must stay null rather than defaulting to some placeholder.
    expect(result.changeSet).toBeNull();
  });

  it("captures the mockDataChangeSet event", async () => {
    const response = sseResponse(
      'event: mockDataChangeSet\ndata: {"changeSetId":"c1","summary":"1 record","operations":[]}\n\n' +
        'event: done\ndata: {"messageId":"m1","model":"x","finishReason":"stop","citedIndexes":[],"groundingWarnings":[],"intent":"codebase_question","retrievalAttempts":0}\n\n',
    );
    let captured: unknown = null;
    const result = await consumeMockDataStream(response, {
      onCitations: () => {},
      onToken: () => {},
      onChangeSet: (changeSet) => {
        captured = changeSet;
      },
    });
    expect(result.changeSet?.changeSetId).toBe("c1");
    expect(captured).not.toBeNull();
  });

  it("captures the error terminator when the turn fails mid-stream", async () => {
    // Exactly one terminator arrives per turn -- `done` or `error`, never both -- and
    // it carries a `finishReason` the caller can act on.
    const response = sseResponse(
      'event: citations\ndata: {"citations":[]}\n\n' +
        'event: token\ndata: {"text":"Partial"}\n\n' +
        'event: error\ndata: {"messageId":null,"code":"LLM_UNAVAILABLE","message":"The model did not respond.","finishReason":"error"}\n\n',
    );
    const result = await consumeMockDataStream(response, {
      onCitations: () => {},
      onToken: () => {},
      onChangeSet: () => {},
    });
    expect(result.content).toBe("Partial");
    expect(result.done).toBeNull();
    expect(result.error?.code).toBe("LLM_UNAVAILABLE");
    expect(result.error?.finishReason).toBe("error");
  });
});

import { describe, expect, it } from "vitest";

import type { DoneEventPayload, StatusEventPayload } from "@/lib/api/types";
import { createSseDecoder, parseSseStream } from "@/lib/ask/sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(chunks: string[]) {
  const events = [];
  for await (const event of parseSseStream(streamOf(chunks))) events.push(event);
  return events;
}

describe("createSseDecoder", () => {
  it("emits nothing until a frame is complete", () => {
    const decoder = createSseDecoder();
    expect(decoder.push('event: token\ndata: {"text":"he')).toEqual([]);
  });

  it("reassembles a frame split across two network chunks", () => {
    const decoder = createSseDecoder();
    decoder.push('event: token\ndata: {"text":"hel');
    const events = decoder.push('lo"}\n\n');
    expect(events).toEqual([{ event: "token", data: { text: "hello" } }]);
  });

  it("skips keep-alive comments without parsing them", () => {
    // The backend sends `: keep-alive` every 15 seconds during any gap.
    const decoder = createSseDecoder();
    expect(decoder.push(": keep-alive\n\n")).toEqual([]);
  });

  it("joins a multi-line data field before parsing it", () => {
    // SSE allows one payload to span several `data:` lines; they are rejoined with a
    // newline and parsed once. Note the rejoined text must itself be valid JSON — a
    // raw newline *inside* a JSON string is not legal, so a payload is only ever
    // split between tokens, as here.
    const decoder = createSseDecoder();
    const events = decoder.push('event: token\ndata: {"text":\ndata: "hello"}\n\n');
    expect(events[0]?.data).toEqual({ text: "hello" });
  });

  it("emits several frames arriving in one chunk", () => {
    const decoder = createSseDecoder();
    const events = decoder.push(
      'event: status\ndata: {"phase":"retrieving"}\n\nevent: token\ndata: {"text":"x"}\n\n',
    );
    expect(events.map((e) => e.event)).toEqual(["status", "token"]);
  });
});

describe("M3 stream fields", () => {
  it("parses the classifying and grading phases", () => {
    const decoder = createSseDecoder();
    const events = decoder.push(
      'event: status\ndata: {"phase":"classifying"}\n\nevent: status\ndata: {"phase":"grading"}\n\n',
    );

    // Typed as StatusEventPayload["phase"][], not string[]: this line only compiles
    // once "classifying" and "grading" are members of the phase union in types.ts.
    const expectedPhases: StatusEventPayload["phase"][] = ["classifying", "grading"];
    const phases = events.map((e) => (e.data as StatusEventPayload).phase);
    expect(phases).toEqual(expectedPhases);
  });

  it("carries the intent and attempt count on done", () => {
    const decoder = createSseDecoder();
    const events = decoder.push(
      'event: done\ndata: {"messageId":"m","model":"x","finishReason":"stop","citedIndexes":[],"groundingWarnings":[],"intent":"conversational","retrievalAttempts":0}\n\n',
    );

    const payload = events[0]?.data as DoneEventPayload;
    expect(payload.intent).toBe("conversational");
    expect(payload.retrievalAttempts).toBe(0);
  });
});

describe("parseSseStream", () => {
  it("yields events in order", async () => {
    const events = await collect([
      'event: status\ndata: {"phase":"retrieving"}\n\n',
      'event: citations\ndata: {"citations":[]}\n\n',
      'event: token\ndata: {"text":"hi"}\n\n',
      'event: done\ndata: {"messageId":"m1"}\n\n',
    ]);
    expect(events.map((e) => e.event)).toEqual([
      "status",
      "citations",
      "token",
      "done",
    ]);
  });

  it("ignores an unknown event rather than throwing", async () => {
    // M3 will add events to this stream. A client that throws on one it does not
    // recognise turns a backend feature addition into a frontend outage.
    const events = await collect([
      'event: reasoning\ndata: {"step":"critique"}\n\n',
      'event: token\ndata: {"text":"hi"}\n\n',
    ]);
    expect(events.map((e) => e.event)).toEqual(["reasoning", "token"]);
  });

  it("drops a frame whose data is not valid JSON, and keeps going", async () => {
    const events = await collect([
      "event: token\ndata: {not json\n\n",
      'event: token\ndata: {"text":"ok"}\n\n',
    ]);
    expect(events).toEqual([{ event: "token", data: { text: "ok" } }]);
  });

  it("yields nothing for a stream that closes empty", async () => {
    expect(await collect([])).toEqual([]);
  });

  it("defaults a frame with no event line to `message`", async () => {
    const events = await collect(['data: {"text":"x"}\n\n']);
    expect(events[0]?.event).toBe("message");
  });
});

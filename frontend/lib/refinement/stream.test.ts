import { describe, expect, it, vi } from "vitest";

import {
  consumeRefinementStream,
  type ChangeSetEventName,
} from "@/lib/refinement/stream";

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

const DONE =
  'event: done\ndata: {"messageId":"m","model":"x","finishReason":"stop","citedIndexes":[],"groundingWarnings":[],"intent":"codebase_question","retrievalAttempts":1}\n\n';

function handlers(overrides: Record<string, unknown> = {}) {
  return { onCitations: vi.fn(), onToken: vi.fn(), onChangeSet: vi.fn(), ...overrides };
}

describe.each<ChangeSetEventName>(["changeSet", "mockDataChangeSet"])(
  "consumeRefinementStream (%s)",
  (eventName) => {
    it("delivers citations before the first token, on every route", async () => {
      /** A client must not need to know which route it got in order to parse the
       * stream, so `citations` is emitted exactly once even when it is empty. */
      const order: string[] = [];

      await consumeRefinementStream(
        streamOf([
          'event: citations\ndata: {"citations":[]}\n\n',
          'event: token\ndata: {"text":"hi"}\n\n',
          DONE,
        ]),
        eventName,
        {
          onCitations: () => order.push("citations"),
          onToken: () => order.push("token"),
          onChangeSet: () => order.push("changeSet"),
        },
      );

      expect(order).toEqual(["citations", "token"]);
    });

    it("collects tokens, the phase and the change set named for this chat", async () => {
      const onChangeSet = vi.fn();
      const onPhase = vi.fn();

      const result = await consumeRefinementStream<{ changeSetId: string }>(
        streamOf([
          'event: status\ndata: {"phase":"retrieving"}\n\n',
          'event: citations\ndata: {"citations":[]}\n\n',
          'event: token\ndata: {"text":"Add "}\n\n',
          'event: token\ndata: {"text":"one."}\n\n',
          `event: ${eventName}\ndata: {"changeSetId":"cs1","summary":"1 added","operations":[]}\n\n`,
          DONE,
        ]),
        eventName,
        handlers({ onChangeSet, onPhase }),
      );

      expect(onPhase).toHaveBeenCalledWith("retrieving");
      expect(onChangeSet).toHaveBeenCalledOnce();
      expect(result.changeSet?.changeSetId).toBe("cs1");
      expect(result.content).toBe("Add one.");
      expect(result.done?.finishReason).toBe("stop");
    });

    it("ignores the other chat's change-set event", async () => {
      const other = eventName === "changeSet" ? "mockDataChangeSet" : "changeSet";
      const onChangeSet = vi.fn();

      const result = await consumeRefinementStream(
        streamOf([`event: ${other}\ndata: {"changeSetId":"x"}\n\n`, DONE]),
        eventName,
        handlers({ onChangeSet }),
      );

      expect(onChangeSet).not.toHaveBeenCalled();
      expect(result.changeSet).toBeNull();
    });

    it("survives a turn that proposes nothing", async () => {
      /** "Why does this expect 410?" is a legitimate turn that changes nothing. */
      const result = await consumeRefinementStream(
        streamOf([
          'event: citations\ndata: {"citations":[]}\n\n',
          'event: token\ndata: {"text":"Because the route is gone."}\n\n',
          DONE,
        ]),
        eventName,
        handlers(),
      );

      expect(result.changeSet).toBeNull();
      expect(result.error).toBeNull();
    });

    it("ignores an event name it does not know", async () => {
      const result = await consumeRefinementStream(
        streamOf(['event: somethingNew\ndata: {"x":1}\n\n', DONE]),
        eventName,
        handlers(),
      );

      expect(result.done).not.toBeNull();
    });

    it("captures the error terminator when the turn fails mid-stream", async () => {
      const result = await consumeRefinementStream(
        streamOf([
          'event: token\ndata: {"text":"Partial"}\n\n',
          'event: error\ndata: {"messageId":null,"code":"LLM_UNAVAILABLE","message":"The model did not respond.","finishReason":"error"}\n\n',
        ]),
        eventName,
        handlers(),
      );

      expect(result.content).toBe("Partial");
      expect(result.done).toBeNull();
      expect(result.error?.code).toBe("LLM_UNAVAILABLE");
      expect(result.finishReason).toBe("error");
    });

    it("keeps the finishReason of a done terminator", async () => {
      const result = await consumeRefinementStream(
        streamOf([
          'event: done\ndata: {"messageId":"m1","model":"x","finishReason":"timeout","citedIndexes":[],"groundingWarnings":[]}\n\n',
        ]),
        eventName,
        handlers(),
      );

      expect(result.finishReason).toBe("timeout");
    });

    it("keeps the finishReason of an error terminator", async () => {
      const result = await consumeRefinementStream(
        streamOf([
          'event: error\ndata: {"messageId":"m1","code":"LLM_UNAVAILABLE","message":"Too slow.","finishReason":"timeout"}\n\n',
        ]),
        eventName,
        handlers(),
      );

      expect(result.finishReason).toBe("timeout");
    });

    it("has a null finishReason when the stream ends with no terminator", async () => {
      const result = await consumeRefinementStream(
        streamOf(['event: token\ndata: {"text":"partial"}\n\n']),
        eventName,
        handlers(),
      );

      expect(result.finishReason).toBeNull();
    });
  },
);

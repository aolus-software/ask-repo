import { describe, expect, it } from "vitest";

import { type AskState, initialAskState, reduceAskEvent } from "@/hooks/use-ask-stream";

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

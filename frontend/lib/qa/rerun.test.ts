import { describe, expect, it } from "vitest";

import { initialRerunState, rerunReducer } from "@/lib/qa/rerun";

const citations = { citations: [{ index: 1, filePath: "a.py" }] };

describe("rerunReducer", () => {
  it("collects citations before any token, per the ordering contract", () => {
    let state = initialRerunState;
    state = rerunReducer(state, { event: "citations", data: citations });
    state = rerunReducer(state, { event: "token", data: { text: "Hello" } });

    expect(state.citations).toHaveLength(1);
    expect(state.answer).toBe("Hello");
  });

  it("appends tokens in order", () => {
    let state = initialRerunState;
    for (const text of ["a", "b", "c"]) {
      state = rerunReducer(state, { event: "token", data: { text } });
    }

    expect(state.answer).toBe("abc");
  });

  it("marks the run finished on done and records the finish reason", () => {
    let state = rerunReducer(initialRerunState, {
      event: "token",
      data: { text: "x" },
    });
    state = rerunReducer(state, {
      event: "done",
      data: { messageId: null, finishReason: "stop", groundingWarnings: [] },
    });

    expect(state.status).toBe("finished");
    expect(state.finishReason).toBe("stop");
  });

  it("treats error as a terminator too, so the panel never hangs", () => {
    const state = rerunReducer(initialRerunState, {
      event: "error",
      data: {
        messageId: null,
        code: "LLM_UNAVAILABLE",
        message: "down",
        finishReason: "error",
      },
    });

    expect(state.status).toBe("finished");
    expect(state.finishReason).toBe("error");
    expect(state.error).toBe("down");
  });

  it("keeps a partial answer when the stream ends without a terminator", () => {
    let state = rerunReducer(initialRerunState, {
      event: "token",
      data: { text: "half" },
    });
    state = rerunReducer(state, { event: "__closed", data: {} });

    expect(state.answer).toBe("half");
    expect(state.finishReason).toBe("disconnected");
  });
});

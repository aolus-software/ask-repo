import type { CitationPayload, FinishReason } from "@/lib/api/types";
import type { SseEvent } from "@/lib/ask/sse";

export interface RerunState {
  status: "idle" | "streaming" | "finished";
  answer: string;
  citations: CitationPayload[];
  groundingWarnings: string[];
  finishReason: FinishReason | null;
  error: string | null;
}

export const initialRerunState: RerunState = {
  status: "idle",
  answer: "",
  citations: [],
  groundingWarnings: [],
  finishReason: null,
  error: null,
};

/**
 * Pure, so the ordering contract is testable without a network or React.
 *
 * `__closed` is synthesised by the caller when the stream ends without a
 * terminator. Without it a disconnect would leave the panel spinning forever on a
 * partial answer the server has already stored.
 */
export function rerunReducer(state: RerunState, event: SseEvent): RerunState {
  switch (event.event) {
    case "status":
      return { ...state, status: "streaming" };
    case "citations":
      return {
        ...state,
        status: "streaming",
        citations: (event.data as { citations: CitationPayload[] }).citations,
      };
    case "token":
      return {
        ...state,
        status: "streaming",
        answer: state.answer + (event.data as { text: string }).text,
      };
    case "done": {
      const data = event.data as {
        finishReason: FinishReason;
        groundingWarnings: string[];
      };
      return {
        ...state,
        status: "finished",
        finishReason: data.finishReason,
        groundingWarnings: data.groundingWarnings ?? [],
      };
    }
    case "error": {
      const data = event.data as { finishReason: FinishReason; message: string };
      return {
        ...state,
        status: "finished",
        finishReason: data.finishReason,
        error: data.message,
      };
    }
    case "__closed":
      return state.status === "finished"
        ? state
        : { ...state, status: "finished", finishReason: "disconnected" };
    default:
      return state;
  }
}

"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

import { apiFetchRaw } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type {
  CitationPayload,
  CitationsEventPayload,
  DoneEventPayload,
  ErrorEventPayload,
  FinishReason,
  StatusEventPayload,
  TokenEventPayload,
} from "@/lib/api/types";
import { type SseEvent, parseSseStream } from "@/lib/ask/sse";
import { keys } from "@/lib/query/keys";

export interface AskState {
  phase: string | null;
  citations: CitationPayload[];
  text: string;
  isStreaming: boolean;
  /** `interrupted` is the stream simply ending with no terminator. */
  terminal: "done" | "error" | "interrupted" | null;
  finishReason: FinishReason | null;
  citedIndexes: number[];
  groundingWarnings: string[];
  errorMessage: string | null;
}

export function initialAskState(): AskState {
  return {
    phase: null,
    citations: [],
    text: "",
    isStreaming: true,
    terminal: null,
    finishReason: null,
    citedIndexes: [],
    groundingWarnings: [],
    errorMessage: null,
  };
}

/**
 * The ordering contract (`.claude/rules/rag.md`), as a pure reducer so it is tested
 * without React:
 *   - `citations` exactly once, always before the first token;
 *   - exactly one terminator, `done` or `error`, both carrying finishReason;
 *   - an unknown event is ignored, never fatal.
 */
export function reduceAskEvent(state: AskState, event: SseEvent): AskState {
  switch (event.event) {
    case "status":
      return { ...state, phase: (event.data as StatusEventPayload).phase };
    case "citations":
      return { ...state, citations: (event.data as CitationsEventPayload).citations };
    case "token":
      return { ...state, text: state.text + (event.data as TokenEventPayload).text };
    case "done": {
      const payload = event.data as DoneEventPayload;
      return {
        ...state,
        isStreaming: false,
        terminal: "done",
        finishReason: payload.finishReason,
        citedIndexes: payload.citedIndexes ?? [],
        groundingWarnings: payload.groundingWarnings ?? [],
      };
    }
    case "error": {
      const payload = event.data as ErrorEventPayload;
      return {
        ...state,
        isStreaming: false,
        terminal: "error",
        finishReason: payload.finishReason,
        errorMessage: payload.message,
      };
    }
    default:
      return state;
  }
}

export function useAskStream(conversationId: string) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<AskState | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const ask = useCallback(
    async (question: string) => {
      const controller = new AbortController();
      abortRef.current?.abort();
      abortRef.current = controller;

      let current = initialAskState();
      let started = false;

      // Tokens accumulate locally and flush on an animation frame: a long answer is
      // thousands of fragments, and a setState per fragment re-renders the markdown
      // tree thousands of times.
      let frameHandle: number | null = null;
      const flush = () => {
        frameHandle = null;
        setState(current);
      };
      const schedule = () => {
        frameHandle ??= requestAnimationFrame(flush);
      };

      try {
        // Everything that can legitimately return a status other than 200 happens
        // before the body starts (rag.md: the pre-flight/stream split). Those errors
        // are RETHROWN so the caller can render them where the question was asked;
        // only failures after the first event become stream state. Without this
        // split, PROJECT_NOT_READY and EMBEDDING_MODEL_CHANGED would be swallowed
        // into a generic "the answer stopped".
        const response = await apiFetchRaw(
          endpoints.conversations.messages(conversationId),
          {
            method: "POST",
            body: JSON.stringify({ question }),
            signal: controller.signal,
          },
        );

        if (!response.body) throw new Error("The server sent no answer stream.");

        setState(current);
        started = true;

        for await (const event of parseSseStream(response.body, controller.signal)) {
          current = reduceAskEvent(current, event);
          if (event.event === "token") schedule();
          else setState(current);
        }

        // No terminator means the connection dropped. The backend has already
        // persisted the partial with finishReason "disconnected", so the UI marks
        // the answer interrupted rather than pretending it completed.
        if (!current.terminal) {
          current = {
            ...current,
            isStreaming: false,
            terminal: "interrupted",
            finishReason: "disconnected",
          };
        }
      } catch (error) {
        if (controller.signal.aborted) return;

        // Pre-flight: nothing was streamed, so the caller owns this error.
        if (!started) {
          setState(null);
          throw error;
        }

        current = {
          ...current,
          isStreaming: false,
          terminal: "error",
          finishReason: "error",
          errorMessage: error instanceof Error ? error.message : "The answer failed.",
        };
      } finally {
        if (frameHandle !== null) cancelAnimationFrame(frameHandle);
        if (started) setState(current);

        // After ANY of the three terminations: the refetch is the reconciliation
        // point. The optimistic message is replaced by the stored one, which is where
        // the real messageId and the resolved `cited` flags come from.
        void queryClient.invalidateQueries({
          queryKey: keys.conversations.detail(conversationId),
        });
        // The backend derives the title from the first question, so the rail is stale too.
        void queryClient.invalidateQueries({ queryKey: keys.conversations.all });
      }
    },
    [conversationId, queryClient],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState(null);
  }, []);

  return { state, ask, reset };
}

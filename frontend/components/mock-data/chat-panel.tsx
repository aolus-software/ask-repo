"use client";

import { Info } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Answer } from "@/components/ask/answer";
import { Composer } from "@/components/ask/composer";
import { MessageList } from "@/components/ask/message-list";
import { Sources } from "@/components/ask/sources";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, apiFetchRaw } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { endpoints } from "@/lib/api/endpoints";
import type { CitationPayload, MockDataMessageResponse } from "@/lib/api/types";
import { consumeMockDataStream } from "@/lib/mock-data/stream";
import { keys } from "@/lib/query/keys";

interface TurnState {
  citations: CitationPayload[];
  citedIndexes: number[];
  text: string;
  isStreaming: boolean;
  errorMessage: string | null;
  reconciled: boolean;
}

function initialTurnState(): TurnState {
  return {
    citations: [],
    citedIndexes: [],
    text: "",
    isStreaming: true,
    errorMessage: null,
    reconciled: false,
  };
}

/**
 * The module's shared mock-data refinement chat. Structurally identical to
 * `components/checklist/chat-panel.tsx`'s `ChatPanel` -- see that component for why
 * each piece of state exists (the `reconciled` flag, the per-frame token batching,
 * the pre-flight/mid-stream error split). Kept as a separate component rather than a
 * parameterised shared one so this feature and the checklist's own chat can diverge
 * without a shared file changing under both.
 */
export function MockDataChatPanel({
  moduleId,
  hasPendingChangeSet,
}: {
  moduleId: string;
  hasPendingChangeSet: boolean;
}) {
  const queryClient = useQueryClient();

  const messages = useQuery({
    queryKey: keys.mockDataMessages.forModule(moduleId),
    queryFn: () =>
      apiFetch<MockDataMessageResponse[]>(endpoints.mockData.messages(moduleId)),
  });

  const [turn, setTurn] = useState<TurnState | null>(null);
  const [preflightError, setPreflightError] = useState<unknown>(null);
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (question: string) => {
      const controller = new AbortController();
      abortRef.current?.abort();
      abortRef.current = controller;

      let current = initialTurnState();
      let started = false;
      let frameHandle: number | null = null;
      const flush = () => {
        frameHandle = null;
        setTurn(current);
      };
      const scheduleFlush = () => {
        frameHandle ??= requestAnimationFrame(flush);
      };

      try {
        const response = await apiFetchRaw(endpoints.mockData.messages(moduleId), {
          method: "POST",
          body: JSON.stringify({ question }),
          signal: controller.signal,
        });

        setTurn(current);
        started = true;

        void queryClient.invalidateQueries({
          queryKey: keys.mockDataMessages.forModule(moduleId),
        });

        const result = await consumeMockDataStream(response, {
          onCitations: (citations) => {
            current = { ...current, citations };
            setTurn(current);
          },
          onToken: (text) => {
            current = { ...current, text: current.text + text };
            scheduleFlush();
          },
          onChangeSet: () => {
            void queryClient.invalidateQueries({ queryKey: keys.mockData.detail(moduleId) });
          },
        });

        if (result.error) {
          current = { ...current, isStreaming: false, errorMessage: result.error.message };
        } else if (result.done) {
          current = {
            ...current,
            isStreaming: false,
            citedIndexes: result.done.citedIndexes,
          };
        } else {
          current = {
            ...current,
            isStreaming: false,
            errorMessage: "The connection dropped. What arrived above is kept.",
          };
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        if (!started) {
          setPreflightError(error);
          return;
        }
        current = {
          ...current,
          isStreaming: false,
          errorMessage: error instanceof Error ? error.message : "The reply stopped.",
        };
      } finally {
        if (frameHandle !== null) cancelAnimationFrame(frameHandle);
        if (started) setTurn(current);
        await queryClient.invalidateQueries({
          queryKey: keys.mockDataMessages.forModule(moduleId),
        });
        if (started && abortRef.current === controller) {
          setTurn({ ...current, reconciled: true });
        }
      }
    },
    [moduleId, queryClient],
  );

  const isStreaming = turn?.isStreaming ?? false;
  const composerDisabled = isStreaming || hasPendingChangeSet;
  const composerPlaceholder = hasPendingChangeSet
    ? "Apply or discard the pending changes first."
    : isStreaming
      ? "Answering…"
      : "Ask for a specific shape, or say what you'd like changed";

  return (
    <div className="space-y-6">
      <Alert>
        <Info />
        <AlertTitle>This chat is shared</AlertTitle>
        <AlertDescription>
          Everyone on this instance can read this conversation.
        </AlertDescription>
      </Alert>

      {messages.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : messages.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load this chat</AlertTitle>
          <AlertDescription>
            {isApiError(messages.error) ? messages.error.message : "Try again."}
          </AlertDescription>
        </Alert>
      ) : messages.data && messages.data.length > 0 ? (
        <MessageList messages={messages.data} />
      ) : (
        <p className="text-muted-foreground text-sm">
          No messages yet. Ask for the dataset to be refined, or explain what should change.
        </p>
      )}

      {turn ? (
        <div>
          {!turn.reconciled ? (
            <>
              <Sources citations={turn.citations} citedIndexes={turn.citedIndexes} />
              <Answer content={turn.text} />
            </>
          ) : null}
          {turn.errorMessage ? (
            <Alert className="border-danger mt-4">
              <AlertTitle className="text-danger">The reply stopped</AlertTitle>
              <AlertDescription>{turn.errorMessage}</AlertDescription>
            </Alert>
          ) : null}
        </div>
      ) : null}

      {preflightError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not send that</AlertTitle>
          <AlertDescription>
            {isApiError(preflightError) ? preflightError.message : "Something went wrong."}
          </AlertDescription>
        </Alert>
      ) : null}

      <Composer
        onSubmit={(question) => {
          setPreflightError(null);
          void send(question);
        }}
        disabled={composerDisabled}
        placeholder={composerPlaceholder}
      />
    </div>
  );
}

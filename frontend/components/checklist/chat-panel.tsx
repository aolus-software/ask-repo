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
import type { ChecklistMessageResponse, CitationPayload } from "@/lib/api/types";
import { consumeChecklistStream } from "@/lib/checklist/stream";
import { keys } from "@/lib/query/keys";

interface TurnState {
  citations: CitationPayload[];
  citedIndexes: number[];
  text: string;
  isStreaming: boolean;
  errorMessage: string | null;
  /**
   * The stored turn has landed in the messages query.
   *
   * Until it does, the reply exists only in this state and this panel is the only
   * place rendering it. After it does, `MessageList` renders the same text from the
   * persisted row above, so this copy stops rendering -- without that switch the
   * reply would appear twice until a reload (mirrors `AskState.reconciled` in
   * `hooks/use-ask-stream.ts`).
   */
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
 * The module's shared refinement chat: history plus a composer that streams a new
 * turn through the same graph and the same SSE contract the Ask screen uses
 * (`.claude/rules/rag.md`).
 *
 * `hasPendingChangeSet` is a prop, not a query, on purpose: the screen already reads
 * `pendingChangeSetId` off the module detail for the Review-changes banner, and a
 * second fetch here would be a second place that "is one pending" fact could drift
 * from the first.
 */
export function ChatPanel({
  moduleId,
  hasPendingChangeSet,
}: {
  moduleId: string;
  hasPendingChangeSet: boolean;
}) {
  const queryClient = useQueryClient();

  const messages = useQuery({
    queryKey: keys.checklistMessages.forModule(moduleId),
    queryFn: () =>
      apiFetch<ChecklistMessageResponse[]>(
        endpoints.checklistModules.messages(moduleId),
      ),
    // Remounting must re-read the server, not the cache. The global `staleTime` is
    // 30s (`lib/query/client.ts`), and the assistant row is committed server-side
    // under the shield in `finally` (`.claude/rules/rag.md`) -- after the last SSE
    // byte, so the turn-end refetch below can land just before it. That caches a
    // list missing the reply and marks it fresh, and navigating away and back inside
    // the window then serves it. `"always"` still renders the cache first, so this
    // costs a background request, not a spinner.
    refetchOnMount: "always",
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

      // Tokens are batched to one setState per animation frame, the same reason
      // `useAskStream` does it: a long reply is thousands of fragments, and a
      // setState per fragment re-renders the markdown tree thousands of times.
      let frameHandle: number | null = null;
      const flush = () => {
        frameHandle = null;
        setTurn(current);
      };
      const scheduleFlush = () => {
        frameHandle ??= requestAnimationFrame(flush);
      };

      try {
        // Everything that can still choose a status code runs in `prepare_turn`,
        // before the first byte of the stream -- a non-2xx here throws before
        // `started` flips, so the catch below can tell a pre-flight rejection (a
        // stale pending-change-set race, an embedding-model change) from a failure
        // mid-stream. Same split as `useAskStream`.
        const response = await apiFetchRaw(
          endpoints.checklistModules.messages(moduleId),
          {
            method: "POST",
            body: JSON.stringify({ question }),
            signal: controller.signal,
          },
        );

        setTurn(current);
        started = true;

        // The user's turn is persisted by `prepare_turn`, before the first stream
        // byte -- refetch now so it appears in the history for the length of the
        // reply, rather than only once the whole turn settles.
        void queryClient.invalidateQueries({
          queryKey: keys.checklistMessages.forModule(moduleId),
        });

        const result = await consumeChecklistStream(response, {
          onCitations: (citations) => {
            current = { ...current, citations };
            setTurn(current);
          },
          onToken: (text) => {
            current = { ...current, text: current.text + text };
            scheduleFlush();
          },
          onChangeSet: () => {
            // The banner that follows is the module detail query's business --
            // this panel never renders the diff itself (`ChangeSetPanel` owns
            // that, and two diff renderers would drift).
            void queryClient.invalidateQueries({
              queryKey: keys.checklistModules.detail(moduleId),
            });
          },
        });

        if (result.error) {
          current = {
            ...current,
            isStreaming: false,
            errorMessage: result.error.message,
          };
        } else if (result.done) {
          current = {
            ...current,
            isStreaming: false,
            citedIndexes: result.done.citedIndexes,
          };
        } else {
          // No terminator arrived: the connection dropped. The backend has already
          // persisted the partial turn under a "disconnected" finishReason -- what
          // streamed above is kept, not discarded (the shielded write this exists
          // for, `.claude/rules/rag.md`).
          current = {
            ...current,
            isStreaming: false,
            errorMessage: "The connection dropped. What arrived above is kept.",
          };
        }
      } catch (error) {
        if (controller.signal.aborted) return;

        // Pre-flight: nothing was streamed, so the composer owns reporting this.
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

        // The reconciliation point: the persisted pair replaces the in-flight
        // bubble once it lands. Awaited, not fired and forgotten, so `reconciled`
        // is set only once the stored row is actually there to take over.
        await queryClient.invalidateQueries({
          queryKey: keys.checklistMessages.forModule(moduleId),
        });

        // Guarded on the controller: a newer send() owns the state by now, and
        // marking ITS state reconciled would blank a reply that is still streaming.
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
      : "Ask a follow-up, or say what you'd like changed";

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
          No messages yet. Ask for the checklist to be refined, or explain what should
          change.
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
            {isApiError(preflightError)
              ? preflightError.message
              : "Something went wrong."}
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

"use client";

import { Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Answer } from "@/components/ask/answer";
import { AssistantTurn } from "@/components/ask/assistant-turn";
import { Composer } from "@/components/ask/composer";
import { GroundingNotice } from "@/components/ask/grounding-notice";
import { InterruptedNote } from "@/components/ask/interrupted-note";
import { MessageList } from "@/components/ask/message-list";
import { Sources } from "@/components/ask/sources";
import { EmptyState } from "@/components/feedback/empty-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, apiFetchRaw } from "@/lib/api/client";
import { useErrorText } from "@/lib/i18n/error-text";
import { endpoints } from "@/lib/api/endpoints";
import { usePhaseLabel } from "@/hooks/use-phase-label";
import type { CitationPayload, MockDataMessageResponse } from "@/lib/api/types";
import { consumeMockDataStream } from "@/lib/mock-data/stream";
import { keys } from "@/lib/query/keys";

interface TurnState {
  phase: string | null;
  citations: CitationPayload[];
  citedIndexes: number[];
  groundingWarnings: string[];
  text: string;
  isStreaming: boolean;
  /** `interrupted` is the stream simply ending with no terminator — a client
   * disconnect, not a failure (`.claude/rules/rag.md`), so it renders as the same
   * quiet note the Ask screen uses, never the destructive `Alert` a real `error`
   * gets (`docs/audit-finding-solved-logs.md` §U8.6). */
  terminal: "done" | "error" | "interrupted" | null;
  errorMessage: string | null;
  reconciled: boolean;
}

function initialTurnState(): TurnState {
  return {
    phase: null,
    citations: [],
    citedIndexes: [],
    groundingWarnings: [],
    text: "",
    isStreaming: true,
    terminal: null,
    errorMessage: null,
    reconciled: false,
  };
}

/**
 * The module's shared mock-data refinement chat. Structurally identical to
 * `components/checklist/chat-panel.tsx`'s `ChatPanel` -- see that component for why
 * each piece of state exists (the `reconciled` flag, the per-frame token batching,
 * the pre-flight/mid-stream error split, the phase label, the grounding notice). Kept
 * as a separate component rather than a parameterised shared one so this feature and
 * the checklist's own chat can diverge without a shared file changing under both.
 */
export function MockDataChatPanel({
  moduleId,
  hasPendingChangeSet,
  isGenerating,
  canSend,
}: {
  moduleId: string;
  hasPendingChangeSet: boolean;
  isGenerating: boolean;
  /**
   * Mirrors the backend's `mockdata.edit` gate; it does not replace it. The chat
   * itself stays visible and readable to everyone -- only sending is gated.
   */
  canSend: boolean;
}) {
  const t = useTranslations("mockData.chatPanel");
  const phaseLabel = usePhaseLabel();
  const errorText = useErrorText();
  const queryClient = useQueryClient();

  const messages = useQuery({
    queryKey: keys.mockDataMessages.forModule(moduleId),
    queryFn: () =>
      apiFetch<MockDataMessageResponse[]>(endpoints.mockData.messages(moduleId)),
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
          onPhase: (phase) => {
            current = { ...current, phase };
            setTurn(current);
          },
          onCitations: (citations) => {
            current = { ...current, citations };
            setTurn(current);
          },
          onToken: (text) => {
            current = { ...current, text: current.text + text };
            scheduleFlush();
          },
          onChangeSet: () => {
            void queryClient.invalidateQueries({
              queryKey: keys.mockData.detail(moduleId),
            });
          },
        });

        if (result.error) {
          current = {
            ...current,
            isStreaming: false,
            terminal: "error",
            errorMessage: result.error.message,
          };
        } else if (result.done) {
          current = {
            ...current,
            isStreaming: false,
            terminal: "done",
            citedIndexes: result.done.citedIndexes,
            groundingWarnings: result.done.groundingWarnings ?? [],
          };
        } else {
          // Nothing failed, so this is `interrupted`, not `error` (§U8.6) -- the
          // quiet note, not the destructive Alert.
          current = {
            ...current,
            isStreaming: false,
            terminal: "interrupted",
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
          terminal: "error",
          errorMessage: error instanceof Error ? error.message : t("replyStopped"),
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
    [moduleId, queryClient, t],
  );

  const isStreaming = turn?.isStreaming ?? false;
  const composerDisabled =
    isStreaming || hasPendingChangeSet || isGenerating || !canSend;
  // A generation holds this dataset's lease; refining it by chat while that run is
  // in flight is refused server-side with a 409 (`MockDataDatasetService.prepare_turn`)
  // because writing `review` over a `generating` row would blind the reconcile sweep
  // to a worker that later dies. The composer must not let a user type a paragraph
  // only to have it rejected.
  const composerPlaceholder = !canSend
    ? t("placeholderNoPermission")
    : isGenerating
      ? t("placeholderGenerating")
      : hasPendingChangeSet
        ? t("placeholderPending")
        : isStreaming
          ? t("placeholderAnswering")
          : t("placeholderDefault");

  return (
    <div className="space-y-6">
      <Alert>
        <Info />
        <AlertTitle>{t("sharedTitle")}</AlertTitle>
        <AlertDescription>{t("sharedDescription")}</AlertDescription>
      </Alert>

      {messages.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : messages.isError ? (
        <Alert variant="destructive">
          <AlertTitle>{t("loadErrorTitle")}</AlertTitle>
          <AlertDescription>{errorText(messages.error)}</AlertDescription>
        </Alert>
      ) : messages.data && messages.data.length > 0 ? (
        <MessageList messages={messages.data} feedbackTarget="mock_data_message" />
      ) : (
        <EmptyState size="compact" description={t("empty")} />
      )}

      {turn ? (
        <AssistantTurn>
          {turn.phase && turn.isStreaming ? (
            <p className="text-muted-foreground mb-2 text-sm">
              {phaseLabel(turn.phase)}
            </p>
          ) : null}

          {!turn.reconciled ? (
            <>
              <Sources citations={turn.citations} citedIndexes={turn.citedIndexes} />
              <Answer content={turn.text} />
            </>
          ) : null}

          {/* Not gated on reconciliation, for the same reason the Ask screen does
              not: grounding warnings are not stored on the message
              (`.claude/rules/rag.md`), so this is the only place they are shown. */}
          <GroundingNotice warnings={turn.groundingWarnings} />

          {turn.terminal === "interrupted" && !turn.reconciled ? (
            <InterruptedNote />
          ) : null}

          {turn.terminal === "error" ? (
            <Alert variant="destructive" className="mt-4">
              <AlertTitle>{t("replyStoppedTitle")}</AlertTitle>
              <AlertDescription>{turn.errorMessage}</AlertDescription>
            </Alert>
          ) : null}
        </AssistantTurn>
      ) : null}

      {preflightError ? (
        <Alert variant="destructive">
          <AlertTitle>{t("sendErrorTitle")}</AlertTitle>
          <AlertDescription>{errorText(preflightError)}</AlertDescription>
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

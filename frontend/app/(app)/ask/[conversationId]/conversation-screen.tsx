"use client";

import { useEffect, useRef, useState } from "react";

import { PreflightError } from "@/app/(app)/ask/[conversationId]/preflight-error";
import { Answer } from "@/components/ask/answer";
import { Composer } from "@/components/ask/composer";
import { GroundingNotice } from "@/components/ask/grounding-notice";
import { MessageList } from "@/components/ask/message-list";
import { Sources } from "@/components/ask/sources";
import { NotFound } from "@/components/feedback/not-found";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAskStream } from "@/hooks/use-ask-stream";
import { useConversation } from "@/hooks/use-conversations";
import { takePendingQuestion } from "@/lib/ask/pending";

const PHASE_LABELS: Record<string, string> = {
  queued: "Queued…",
  rewriting: "Understanding the question…",
  retrieving: "Searching the codebase…",
  generating: "Writing the answer…",
};

export function ConversationScreen({ conversationId }: { conversationId: string }) {
  const conversation = useConversation(conversationId);
  const { state, ask } = useAskStream(conversationId);
  const [askError, setAskError] = useState<unknown>(null);
  const askedRef = useRef(false);

  // The first question, handed over by /ask across the navigation. Fired once.
  useEffect(() => {
    if (askedRef.current) return;
    const question = takePendingQuestion(conversationId);
    if (!question) return;
    askedRef.current = true;
    void ask(question).catch(setAskError);
  }, [conversationId, ask]);

  if (conversation.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (conversation.error) {
    // Every miss is 404, on all four routes: a 403 would confirm the conversation
    // exists, and is_admin does not widen this (docs/PRD.md §4.2).
    return <NotFound message="That conversation does not exist." />;
  }

  const detail = conversation.data;
  if (!detail) return <NotFound />;

  const isStreaming = state?.isStreaming ?? false;

  async function handleAsk(question: string) {
    setAskError(null);
    try {
      await ask(question);
    } catch (error) {
      // Pre-flight failures arrive as ordinary HTTP errors before any body, so they
      // render inline in the conversation rather than as a toast (design spec §9.8).
      setAskError(error);
    }
  }

  const lastQuestion =
    detail.messages.findLast((m) => m.role === "user")?.content ?? "";

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-semibold tracking-tight">
        {detail.title ?? "New conversation"}
      </h1>

      <MessageList messages={detail.messages} />

      {state ? (
        <div>
          {state.phase && state.isStreaming ? (
            <p className="text-muted-foreground mb-2 text-sm">
              {PHASE_LABELS[state.phase]}
            </p>
          ) : null}

          {/* Citations render while the answer types — that ordering is the contract. */}
          <Sources citations={state.citations} citedIndexes={state.citedIndexes} />
          <Answer content={state.text} />
          <GroundingNotice warnings={state.groundingWarnings} />

          {state.terminal === "interrupted" ? (
            <p className="text-muted-foreground mt-2 text-xs">
              The connection dropped. What arrived above is kept.
            </p>
          ) : null}

          {state.terminal === "error" ? (
            <Alert className="border-danger mt-4">
              <AlertTitle className="text-danger">The answer stopped</AlertTitle>
              <AlertDescription>{state.errorMessage}</AlertDescription>
            </Alert>
          ) : null}

          {state.finishReason === "timeout" ? (
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => void handleAsk(lastQuestion)}
            >
              Try again
            </Button>
          ) : null}
        </div>
      ) : null}

      {/* Mounted only when there is an error: it queries the project to offer a
          re-index, and that request should not fire on every conversation view. */}
      {askError ? (
        <PreflightError error={askError} projectId={detail.projectId} />
      ) : null}

      <Composer
        onSubmit={(question) => void handleAsk(question)}
        disabled={isStreaming}
        placeholder={isStreaming ? "Answering…" : "Ask a follow-up"}
      />
    </div>
  );
}

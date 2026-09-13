"use client";

import { FolderGit2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { PreflightError } from "@/app/(app)/ask/[conversationId]/preflight-error";
import { Answer } from "@/components/ask/answer";
import { AssistantTurn } from "@/components/ask/assistant-turn";
import { Composer } from "@/components/ask/composer";
import { GroundingNotice } from "@/components/ask/grounding-notice";
import { MessageList } from "@/components/ask/message-list";
import { Sources } from "@/components/ask/sources";
import { DetailError } from "@/components/feedback/detail-error";
import { NotFound } from "@/components/feedback/not-found";
import { ProjectStatusBadge } from "@/components/feedback/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAskStream } from "@/hooks/use-ask-stream";
import { useConversation } from "@/hooks/use-conversations";
import { useProject } from "@/hooks/use-projects";
import { takePendingQuestion } from "@/lib/ask/pending";
import { PHASE_LABELS } from "@/lib/ask/phase-labels";

export function ConversationScreen({ conversationId }: { conversationId: string }) {
  const conversation = useConversation(conversationId);
  // A conversation is bound to one project for its whole life, and every follow-up
  // is answered against it — so which one it is belongs in the header, not only in
  // the error that appears when it stops being answerable. The empty-string fallback
  // is fine: useProject is `enabled` on a non-empty id, so nothing fires until the
  // conversation resolves. PreflightError reads the same query key, so it now hits
  // the cache instead of issuing a second request.
  const project = useProject(conversation.data?.projectId ?? "");
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
    // exists, and is_admin does not widen this (docs/PRD.md §4.2). A network or
    // server failure is neither, and must not read as "deleted" — a conversation is
    // private and unrecoverable, so that claim is exactly the wrong one to guess at
    // (`docs/ui-audit-findings.md` §U7.2).
    return (
      <DetailError
        error={conversation.error}
        notFoundMessage="That conversation does not exist."
        onRetry={() => conversation.refetch()}
      />
    );
  }

  const detail = conversation.data;
  if (!detail) return <NotFound message="That conversation does not exist." />;

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
      {/* Pinned under the navbar so the question you are reading always says which
          conversation and which project it belongs to. */}
      <PageHeader
        sticky
        title={detail.title ?? "New conversation"}
        meta={
          <div className="text-muted-foreground mt-2 flex items-center gap-2 text-sm">
            <FolderGit2 className="size-4 shrink-0" aria-hidden />
            {project.data ? (
              <>
                <Link
                  href={`/projects/${detail.projectId}`}
                  className="text-foreground hover:text-primary font-medium"
                >
                  {project.data.name}
                </Link>
                {/* Shown even when ready: it is the difference between a follow-up
                    that answers and one that returns PROJECT_NOT_READY. */}
                <ProjectStatusBadge status={project.data.status} />
              </>
            ) : project.isError ? (
              <span>That project is no longer available.</span>
            ) : (
              <Skeleton className="h-4 w-40" />
            )}
          </div>
        }
      />

      <MessageList messages={detail.messages} />

      {state ? (
        <AssistantTurn>
          {state.phase && state.isStreaming ? (
            <p className="text-muted-foreground mb-2 text-sm">
              {PHASE_LABELS[state.phase]}
            </p>
          ) : null}

          {/* Citations render while the answer types — that ordering is the contract.
              Both stop rendering once the stored message lands in the list above:
              until then this is the only copy of the answer, after it there are two,
              and rendering both is the answer appearing twice until a reload. */}
          {!state.reconciled ? (
            <>
              <Sources citations={state.citations} citedIndexes={state.citedIndexes} />
              <Answer content={state.text} />
            </>
          ) : null}

          {/* Deliberately NOT gated on reconciliation: grounding warnings are not
              stored on the message (`.claude/rules/rag.md` — they are recomputable,
              so a column would be derived state that can drift), which makes this
              the only place they are ever shown. */}
          <GroundingNotice warnings={state.groundingWarnings} />

          {/* The stored row renders its own interrupted note from finishReason. */}
          {state.terminal === "interrupted" && !state.reconciled ? (
            <p className="text-muted-foreground mt-2 text-xs">
              The connection dropped. What arrived above is kept.
            </p>
          ) : null}

          {state.terminal === "error" ? (
            <Alert variant="destructive" className="mt-4">
              <AlertTitle>The answer stopped</AlertTitle>
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
        </AssistantTurn>
      ) : null}

      {/* Mounted only when there is an error — it is about this turn, not the
          conversation (design spec §9.8). */}
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

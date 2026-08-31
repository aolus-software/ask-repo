"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Answer } from "@/components/ask/answer";
import { GroundingNotice } from "@/components/ask/grounding-notice";
import { Sources } from "@/components/ask/sources";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { FormError } from "@/components/form/form-error";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { apiFetch, apiFetchRaw } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { PendingRunPayload, QAPairDetailResponse } from "@/lib/api/types";
import { parseSseStream } from "@/lib/ask/sse";
import { type RerunState, initialRerunState, rerunReducer } from "@/lib/qa/rerun";
import { keys } from "@/lib/query/keys";

/** Hydrate directly from the stored slot — no stream, no network. */
function stateFromPendingRun(pendingRun: PendingRunPayload): RerunState {
  return {
    status: "finished",
    answer: pendingRun.answer,
    citations: pendingRun.citations ?? [],
    groundingWarnings: [],
    finishReason: pendingRun.finishReason,
    error: null,
  };
}

const FINISH_REASON_LABELS: Record<string, string> = {
  error: "The run failed before finishing, so it cannot be saved.",
  timeout: "The run timed out before finishing, so it cannot be saved.",
  disconnected:
    "The connection dropped before the run finished, so it cannot be saved.",
};

/**
 * Streams a re-run beside the stored answer, or — when the pair already carries a
 * pending run — renders straight from it with no network call at all. That second
 * path is the visible payoff of holding the run server-side (spec §2.5): the work
 * survives a reload, a closed laptop, or a different browser.
 */
export function RerunPanel({
  pair,
  onClose,
}: {
  pair: QAPairDetailResponse;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const startedRef = useRef(false);
  const [confirmingSave, setConfirmingSave] = useState(false);

  // Seeded once, from whatever the pair carried when the panel first mounted. A
  // later refetch (from an unrelated invalidation) must not re-seed this — the
  // panel owns the run once it starts one.
  const [state, setState] = useState<RerunState>(() =>
    pair.pendingRun ? stateFromPendingRun(pair.pendingRun) : initialRerunState,
  );

  useEffect(() => {
    if (startedRef.current || pair.pendingRun) return;
    startedRef.current = true;

    const controller = new AbortController();

    async function run() {
      try {
        const response = await apiFetchRaw(endpoints.qaPairs.rerun(pair.id), {
          method: "POST",
          signal: controller.signal,
        });
        if (!response.body) throw new Error("The server sent no answer stream.");

        for await (const event of parseSseStream(response.body, controller.signal)) {
          setState((current) => rerunReducer(current, event));
        }

        // No terminator means the connection dropped. The server has already
        // stored the partial with pendingFinishReason "disconnected" — see
        // `.claude/rules/rag.md` — so the panel settles rather than spinning.
        setState((current) => rerunReducer(current, { event: "__closed", data: {} }));
      } catch (error) {
        if (controller.signal.aborted) return;
        setState((current) => ({
          ...current,
          status: "finished",
          finishReason: "error",
          error: error instanceof Error ? error.message : "The re-run failed.",
        }));
      }
    }

    void run();
    return () => controller.abort();
    // Runs exactly once per mount — the guard above is what makes a second effect
    // firing (StrictMode, a prop change) a no-op rather than a second stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally mount-once
  }, [pair.id]);

  const accept = useMutation({
    mutationFn: () =>
      apiFetch<QAPairDetailResponse>(endpoints.qaPairs.acceptRerun(pair.id), {
        method: "POST",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.qaPairs.all });
      toast.success("Saved. Status reset to unreviewed.");
      setConfirmingSave(false);
      onClose();
    },
  });

  const discard = useMutation({
    mutationFn: () =>
      apiFetch<void>(endpoints.qaPairs.rerun(pair.id), { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.qaPairs.all });
      toast.success("Re-run discarded");
      onClose();
    },
  });

  const finished = state.status === "finished";
  // Mirrors the server's 409 ANSWER_INCOMPLETE rather than letting the user find
  // it out by clicking (spec §7.3): a partial run may be read, never published.
  const canSave = finished && state.finishReason === "stop";

  return (
    <div className="space-y-4">
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Stored</CardTitle>
          </CardHeader>
          <CardContent>
            {pair.answer ? (
              <>
                <Answer content={pair.answer} />
                <Sources citations={pair.citations ?? []} citedIndexes={[]} />
              </>
            ) : (
              <p className="text-muted-foreground text-sm">Not run yet.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>New run</CardTitle>
            {!finished ? (
              <Loader2 className="text-muted-foreground size-4 animate-spin" />
            ) : null}
          </CardHeader>
          <CardContent>
            {state.answer ? (
              <>
                <Sources citations={state.citations} citedIndexes={[]} />
                <Answer content={state.answer} />
                <GroundingNotice warnings={state.groundingWarnings} />
              </>
            ) : !finished ? (
              <p className="text-muted-foreground text-sm">
                Running against the current index…
              </p>
            ) : null}

            {finished && state.error ? (
              <Alert className="border-danger mt-4">
                <AlertTriangle className="text-danger size-4" />
                <AlertTitle className="text-danger">The re-run stopped</AlertTitle>
                <AlertDescription>{state.error}</AlertDescription>
              </Alert>
            ) : null}

            {finished && !canSave && FINISH_REASON_LABELS[state.finishReason ?? ""] ? (
              <p className="text-muted-foreground mt-4 text-sm">
                {FINISH_REASON_LABELS[state.finishReason ?? ""]}
              </p>
            ) : null}
          </CardContent>

          {finished ? (
            <CardFooter className="justify-end gap-2">
              <FormError error={discard.error} />
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={discard.isPending || accept.isPending}
                onClick={() => discard.mutate()}
              >
                {discard.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
                Discard
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={!canSave || accept.isPending}
                title={canSave ? undefined : "This run cannot be saved."}
                onClick={() => setConfirmingSave(true)}
              >
                <RotateCw className="size-4" />
                Save
              </Button>
            </CardFooter>
          ) : null}
        </Card>
      </div>

      <ConfirmDialog
        open={confirmingSave}
        onOpenChange={setConfirmingSave}
        title="Save this run over the stored answer?"
        description="The stored result is replaced and the status resets to unreviewed — a saved verdict was about the old text, not this one."
        confirmLabel="Save"
        isPending={accept.isPending}
        error={accept.error}
        onConfirm={() => accept.mutate()}
      />
    </div>
  );
}

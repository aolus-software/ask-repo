"use client";

import { Answer } from "@/components/ask/answer";
import { EvalStatusBadge } from "@/components/eval/eval-status-badge";
import { EvalVerdictBadge } from "@/components/eval/eval-verdict-badge";
import { JobFailureAlert } from "@/components/feedback/job-failure-alert";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useEvalRun } from "@/hooks/use-eval";
import type { EvalPair } from "@/lib/api/types";
import { formatAbsolute } from "@/lib/dates";

/** One run's per-pair results: the question, what the assistant said, and how it was judged. */
export function EvalRunSheet({
  runId,
  pairs,
  onClose,
}: {
  runId: string | null;
  pairs: EvalPair[];
  onClose: () => void;
}) {
  const query = useEvalRun(runId ?? "");
  const run = query.data;
  const questions = new Map(pairs.map((pair) => [pair.id, pair.question]));

  return (
    <Sheet open={runId !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <SheetContent className="w-full overflow-y-auto data-[side=right]:sm:max-w-3xl data-[side=right]:lg:max-w-5xl">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            Run results
            {run ? <EvalStatusBadge status={run.status} /> : null}
          </SheetTitle>
          <SheetDescription>
            {run ? formatAbsolute(run.createdAt) : "Loading the run…"}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-4">
          {query.isLoading ? <Skeleton className="h-32 w-full" /> : null}
          {run?.status === "failed" && run.error ? (
            <JobFailureAlert title="Run failed" message={run.error} />
          ) : null}
          {run?.results.map((result) => (
            <section key={result.id} className="space-y-2 rounded-md border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <EvalVerdictBadge verdict={result.verdict} />
                <span className="text-muted-foreground text-xs">
                  Retrieval {result.retrievalHit ? "hit" : "miss"}
                </span>
              </div>
              <p className="text-sm font-medium">
                {questions.get(result.pairId) ?? result.pairId}
              </p>
              <Answer content={result.answer} />
              {result.judgeReason ? (
                <p className="text-muted-foreground text-sm">
                  Judge: {result.judgeReason}
                </p>
              ) : null}
              {result.groundingWarnings.length > 0 ? (
                <p className="text-warning text-xs">
                  Warnings: {result.groundingWarnings.join(", ")}
                </p>
              ) : null}
            </section>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}

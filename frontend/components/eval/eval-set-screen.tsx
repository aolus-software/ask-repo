"use client";

import { Play } from "lucide-react";
import { useState } from "react";

import { EvalCompare } from "@/components/eval/eval-compare";
import { EvalPairTable } from "@/components/eval/eval-pair-table";
import { EvalRunSheet } from "@/components/eval/eval-run-sheet";
import { EvalRunTable } from "@/components/eval/eval-run-table";
import { EvalStatusBadge } from "@/components/eval/eval-status-badge";
import { DetailError } from "@/components/feedback/detail-error";
import { JobFailureAlert } from "@/components/feedback/job-failure-alert";
import { NotFound } from "@/components/feedback/not-found";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useEvalRun, useEvalRuns, useEvalSet, useStartEvalRun } from "@/hooks/use-eval";
import { useProject } from "@/hooks/use-projects";
import { can, PERMISSION } from "@/lib/can";
import { formatAbsolute } from "@/lib/dates";
import { toast } from "sonner";

export function EvalSetScreen({
  projectId,
  setId,
}: {
  projectId: string;
  setId: string;
}) {
  const projectQuery = useProject(projectId);
  // Nothing under eval-sets is fetched until the project says the caller may read it.
  const mayRead = projectQuery.data
    ? can(projectQuery.data, PERMISSION.EVAL_READ)
    : false;
  const setQuery = useEvalSet(setId, mayRead);
  const runsQuery = useEvalRuns(setId, mayRead);
  const startRun = useStartEvalRun(setId, projectId);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [baseId, setBaseId] = useState<string | null>(null);
  const [headId, setHeadId] = useState<string | null>(null);
  const baseRun = useEvalRun(baseId ?? "");
  const headRun = useEvalRun(headId ?? "");

  if (projectQuery.isLoading || (mayRead && setQuery.isLoading)) {
    return (
      <div className="mx-auto w-full max-w-7xl space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }
  if (projectQuery.data && !mayRead) return <NotFound />;
  if (setQuery.error) {
    return (
      <DetailError
        error={setQuery.error}
        notFoundMessage="That eval set does not exist, or it has been deleted."
        onRetry={() => setQuery.refetch()}
      />
    );
  }
  const set = setQuery.data;
  const project = projectQuery.data;
  if (!set || !project) return <NotFound />;

  const canRun = can(project, PERMISSION.EVAL_RUN);
  const runs = runsQuery.data?.items ?? [];
  const doneRuns = runs.filter((run) => run.status === "done");
  const running = runs.some((run) => run.status === "running");
  const description = [
    set.sourcePath ?? "Whole project",
    `${set.pairCount} pairs`,
    set.indexedGeneration !== null
      ? `generated from generation ${set.indexedGeneration}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  // Runs arrive newest first, so the oldest is run 1. The number tells apart two
  // runs started in the same second.
  const runLabel = (id: string) => {
    const index = runs.findIndex((candidate) => candidate.id === id);
    if (index < 0) return "Select a run";
    return `Run ${runs.length - index} · ${formatAbsolute(runs[index].createdAt)}`;
  };

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6">
      <PageHeader
        title={set.name}
        titleAddon={<EvalStatusBadge status={set.status} />}
        description={description}
        action={
          canRun ? (
            <Button
              disabled={running || set.status !== "ready" || startRun.isPending}
              onClick={() =>
                startRun.mutate(undefined, {
                  onError: () => toast.error("The run could not be started."),
                })
              }
            >
              <Play className="size-4" />
              Run
            </Button>
          ) : null
        }
      />

      {set.indexedGeneration !== null &&
      set.indexedGeneration !== set.projectGeneration ? (
        <p className="text-muted-foreground text-sm">
          Project is now at generation {set.projectGeneration}.
        </p>
      ) : null}

      {set.status === "failed" && set.error ? (
        <JobFailureAlert title="Generation failed" message={set.error} />
      ) : null}

      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">Pairs</h2>
        <Card className="p-0">
          <EvalPairTable setId={setId} pairs={set.pairs} canRun={canRun} />
        </Card>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold tracking-tight">Runs</h2>
        <Card className="p-0">
          <EvalRunTable runs={runs} onSelect={setSelectedRun} />
        </Card>
      </section>

      {doneRuns.length >= 2 ? (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold tracking-tight">Compare</h2>
          <div className="flex flex-wrap gap-3">
            {(
              [
                ["Base run", baseId, setBaseId],
                ["Head run", headId, setHeadId],
              ] as const
            ).map(([label, value, setValue], position, all) => {
              const otherId = all[1 - position][1];
              return (
                <Select
                  key={label}
                  value={value ?? ""}
                  onValueChange={(next: string | null) => setValue(next || null)}
                >
                  <SelectTrigger className="w-64" aria-label={label}>
                    <SelectValue>
                      {(id: string) => (id ? runLabel(id) : label)}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {doneRuns.map((run) => (
                      <SelectItem
                        key={run.id}
                        value={run.id}
                        disabled={run.id === otherId}
                      >
                        {runLabel(run.id)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              );
            })}
          </div>
          {baseRun.data && headRun.data && baseId && headId ? (
            <Card className="px-4">
              <EvalCompare base={baseRun.data} head={headRun.data} pairs={set.pairs} />
            </Card>
          ) : null}
        </section>
      ) : null}

      <EvalRunSheet
        runId={selectedRun}
        pairs={set.pairs}
        onClose={() => setSelectedRun(null)}
      />
    </div>
  );
}

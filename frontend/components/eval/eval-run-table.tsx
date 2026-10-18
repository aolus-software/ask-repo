"use client";

import { FlaskConical } from "lucide-react";

import { EvalStatusBadge } from "@/components/eval/eval-status-badge";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { EvalRunSummary, EvalSetStatus } from "@/lib/api/types";
import { formatAbsolute } from "@/lib/dates";
import { useFormatRelative } from "@/hooks/use-format-date";

/** Runs of one set, newest first. A row opens the run's results. */
export function EvalRunTable({
  runs,
  onSelect,
  isLoading = false,
  error = null,
  onRetry,
  setStatus = "ready",
}: {
  runs: EvalRunSummary[];
  onSelect: (runId: string) => void;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  /** Only a ready set can be run, so only a ready set is invited to be. */
  setStatus?: EvalSetStatus;
}) {
  const formatRelative = useFormatRelative();
  if (error) {
    return (
      <div className="p-4">
        <ListError error={error} onRetry={() => onRetry?.()} />
      </div>
    );
  }
  if (isLoading) {
    return (
      <Table>
        <TableBody>
          <TableSkeleton columns={4} />
        </TableBody>
      </Table>
    );
  }
  if (runs.length === 0 && setStatus !== "ready") {
    return (
      <EmptyState
        icon={FlaskConical}
        title={setStatus === "generating" ? "Generating questions…" : "No runs"}
        description={
          setStatus === "generating"
            ? "The set can be run once its questions are ready."
            : "A set whose generation failed cannot be run."
        }
      />
    );
  }
  if (runs.length === 0) {
    return (
      <EmptyState
        icon={FlaskConical}
        title="No runs yet"
        description="Run the set to ask each question and judge the answers against the reference."
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Started</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Results</TableHead>
            <TableHead>Model</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => (
            <TableRow
              key={run.id}
              className="cursor-pointer"
              tabIndex={0}
              onClick={() => onSelect(run.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter") onSelect(run.id);
              }}
            >
              <TableCell title={formatAbsolute(run.createdAt)}>
                {formatRelative(run.createdAt)}
              </TableCell>
              <TableCell>
                <EvalStatusBadge status={run.status} />
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                hits {run.hits}/{run.pairsAnswered} · correct {run.correct} · partial{" "}
                {run.partial} · wrong {run.wrong}
                {run.errors > 0 ? ` · errors ${run.errors}` : ""}
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                {run.chatModel ?? "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

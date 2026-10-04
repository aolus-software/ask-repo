"use client";

import { FlaskConical } from "lucide-react";

import { EvalStatusBadge } from "@/components/eval/eval-status-badge";
import { EmptyState } from "@/components/feedback/empty-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { EvalRunSummary } from "@/lib/api/types";
import { formatAbsolute, formatRelative } from "@/lib/dates";

/** Runs of one set, newest first. A row opens the run's results. */
export function EvalRunTable({
  runs,
  onSelect,
}: {
  runs: EvalRunSummary[];
  onSelect: (runId: string) => void;
}) {
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

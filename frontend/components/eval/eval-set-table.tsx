"use client";

import { FlaskConical } from "lucide-react";
import Link from "next/link";

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
import { useEvalSets } from "@/hooks/use-eval";
import type { EvalRunSummary } from "@/lib/api/types";
import { formatAbsolute, formatRelative } from "@/lib/dates";

/** The tally a run's list row shows. Counts only — never a question or an answer. */
function tally(run: EvalRunSummary): string {
  return `hits ${run.hits}/${run.pairsAnswered} · correct ${run.correct} · partial ${run.partial} · wrong ${run.wrong}`;
}

/** Column order is fixed by `docs/design.md`: identity, status, results, timestamps. */
export function EvalSetTable({ projectId }: { projectId: string }) {
  const query = useEvalSets(projectId);
  const sets = query.data?.items ?? [];

  if (query.error) {
    return <ListError error={query.error} onRetry={() => query.refetch()} />;
  }

  if (!query.isLoading && sets.length === 0) {
    return (
      <EmptyState
        icon={FlaskConical}
        title="No eval sets yet"
        description="Generate a set of questions with reference answers, then run it to see how the assistant does on this project."
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Set</TableHead>
            <TableHead>Path</TableHead>
            <TableHead>Pairs</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Latest run</TableHead>
            <TableHead>Created</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {query.isLoading ? (
            <TableSkeleton columns={6} />
          ) : (
            sets.map((set) => (
              <TableRow key={set.id}>
                <TableCell className="font-medium">
                  <Link
                    href={`/projects/${projectId}/eval/${set.id}`}
                    className="hover:text-primary"
                  >
                    {set.name}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground font-mono text-sm">
                  {set.sourcePath ?? <span className="font-sans">Whole project</span>}
                </TableCell>
                <TableCell className="text-sm">{set.pairCount}</TableCell>
                <TableCell>
                  <EvalStatusBadge status={set.status} />
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {set.latestRun ? tally(set.latestRun) : "No runs yet"}
                </TableCell>
                <TableCell
                  className="text-muted-foreground text-sm"
                  title={formatAbsolute(set.createdAt)}
                >
                  {formatRelative(set.createdAt)}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}

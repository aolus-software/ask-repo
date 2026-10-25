"use client";

import { FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";

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

/** Runs of one set, newest first. The start time is a button that opens the run's results. */
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
  const t = useTranslations("eval");
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
        title={
          setStatus === "generating"
            ? t("runTable.generatingTitle")
            : t("runTable.noRunsTitle")
        }
        description={
          setStatus === "generating"
            ? t("runTable.generatingDescription")
            : t("runTable.failedDescription")
        }
      />
    );
  }
  if (runs.length === 0) {
    return (
      <EmptyState
        icon={FlaskConical}
        title={t("runTable.emptyTitle")}
        description={t("runTable.emptyDescription")}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("runTable.columns.started")}</TableHead>
            <TableHead>{t("runTable.columns.status")}</TableHead>
            <TableHead>{t("runTable.columns.results")}</TableHead>
            <TableHead>{t("runTable.columns.model")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.id}>
              <TableCell title={formatAbsolute(run.createdAt)}>
                <button
                  type="button"
                  className="hover:text-primary text-left underline-offset-4 hover:underline"
                  aria-label={t("runTable.openRun", {
                    when: formatRelative(run.createdAt),
                  })}
                  onClick={() => onSelect(run.id)}
                >
                  {formatRelative(run.createdAt)}
                </button>
              </TableCell>
              <TableCell>
                <EvalStatusBadge status={run.status} />
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                {t(run.errors > 0 ? "tally.summaryWithErrors" : "tally.summary", {
                  hits: run.hits,
                  answered: run.pairsAnswered,
                  correct: run.correct,
                  partial: run.partial,
                  wrong: run.wrong,
                  errors: run.errors,
                })}
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

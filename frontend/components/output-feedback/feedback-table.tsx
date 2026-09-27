import { ExternalLink, ThumbsDown, ThumbsUp } from "lucide-react";

import { FEATURE_LABELS } from "@/components/output-feedback/feedback-summary";
import { REASON_LABELS } from "@/components/output-feedback/reason-labels";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { FeedbackAdminRead } from "@/lib/api/types";
import { formatAbsolute, formatRelative } from "@/lib/dates";

/**
 * Column order: when, project, feature, vote, reasons, note, prompt version, and a
 * trace link when there is one. No user column — a `FeedbackAdminRead` carries no
 * voter, and this screen must never show or request one.
 */
export function FeedbackTable({
  rows,
  isLoading,
}: {
  rows: FeedbackAdminRead[];
  isLoading: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>When</TableHead>
            <TableHead>Project</TableHead>
            <TableHead>Feature</TableHead>
            <TableHead>Vote</TableHead>
            <TableHead>Reasons</TableHead>
            <TableHead>Note</TableHead>
            <TableHead>Prompt</TableHead>
            <TableHead className="text-right">Trace</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableSkeleton columns={8} />
          ) : (
            rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell
                  className="text-muted-foreground text-sm"
                  title={formatAbsolute(row.createdAt)}
                >
                  {formatRelative(row.createdAt)}
                </TableCell>
                <TableCell className="text-sm">{row.projectName}</TableCell>
                <TableCell className="text-sm">{FEATURE_LABELS[row.feature]}</TableCell>
                <TableCell>
                  {row.rating === "up" ? (
                    <ThumbsUp className="text-muted-foreground size-4" aria-label="Up" />
                  ) : (
                    <ThumbsDown className="text-muted-foreground size-4" aria-label="Down" />
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {row.reasonCodes.length > 0
                    ? row.reasonCodes.map((code) => REASON_LABELS[code]).join(", ")
                    : "—"}
                </TableCell>
                <TableCell className="max-w-xs text-sm whitespace-pre-wrap">
                  {row.note ?? "—"}
                </TableCell>
                <TableCell className="font-mono text-xs">{row.promptVersion}</TableCell>
                <TableCell className="text-right">
                  {row.traceUrl ? (
                    <a
                      href={row.traceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-muted-foreground hover:text-primary inline-flex"
                      aria-label="Open trace"
                    >
                      <ExternalLink className="size-4" />
                    </a>
                  ) : null}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}

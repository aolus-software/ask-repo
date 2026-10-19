import { ExternalLink, ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "next-intl";

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
import { formatDay } from "@/lib/dates";

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
  const t = useTranslations("outputFeedback");

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("table.when")}</TableHead>
            <TableHead>{t("table.project")}</TableHead>
            <TableHead>{t("table.feature")}</TableHead>
            <TableHead>{t("table.vote")}</TableHead>
            <TableHead>{t("table.reasons")}</TableHead>
            <TableHead>{t("table.note")}</TableHead>
            <TableHead>{t("table.prompt")}</TableHead>
            <TableHead className="text-right">{t("table.trace")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableSkeleton columns={8} />
          ) : (
            rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="text-muted-foreground text-sm">
                  {formatDay(row.createdOn)}
                </TableCell>
                <TableCell className="text-sm">{row.projectName}</TableCell>
                <TableCell className="text-sm">
                  {t(`features.${row.feature}`)}
                </TableCell>
                <TableCell>
                  {row.rating === "up" ? (
                    <ThumbsUp
                      className="text-muted-foreground size-4"
                      aria-label={t("table.up")}
                    />
                  ) : (
                    <ThumbsDown
                      className="text-muted-foreground size-4"
                      aria-label={t("table.down")}
                    />
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {row.reasonCodes.length > 0
                    ? row.reasonCodes.map((code) => t(`reasons.${code}`)).join(", ")
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
                      aria-label={t("table.openTrace")}
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

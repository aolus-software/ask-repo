"use client";

import { FlaskConical, MoreHorizontal, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { DeleteEvalSetDialog } from "@/components/eval/delete-eval-set-dialog";
import { EvalStatusBadge } from "@/components/eval/eval-status-badge";
import { GenerateEvalSetDialog } from "@/components/eval/generate-eval-set-dialog";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { PaginationFooter } from "@/components/layout/pagination-footer";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useEvalSets } from "@/hooks/use-eval";
import { ENDONYMS } from "@/lib/i18n/languages";
import { formatAbsolute } from "@/lib/dates";
import { useFormatRelative } from "@/hooks/use-format-date";

/** Column order is fixed by `docs/design.md`: identity, status, results, timestamps. */
export function EvalSetTable({
  projectId,
  canDelete = false,
  permissions,
}: {
  projectId: string;
  /** The project's permission set. With it, the empty state carries the Generate action. */
  permissions?: string[];
  /** `eval.run`, the permission the delete route checks. The backend still enforces it. */
  canDelete?: boolean;
}) {
  const t = useTranslations("eval");
  const formatRelative = useFormatRelative();
  const [page, setPage] = useState(1);
  const query = useEvalSets(projectId, true, page);
  const [deleting, setDeleting] = useState<{ id: string; name: string } | null>(null);
  const sets = query.data?.items ?? [];

  if (query.error) {
    return <ListError padded error={query.error} onRetry={() => query.refetch()} />;
  }

  if (!query.isLoading && sets.length === 0) {
    return (
      <EmptyState
        icon={FlaskConical}
        title={t("setTable.emptyTitle")}
        description={t("setTable.emptyDescription")}
        action={
          permissions ? (
            <GenerateEvalSetDialog projectId={projectId} permissions={permissions} />
          ) : undefined
        }
      />
    );
  }

  return (
    <>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("setTable.columns.set")}</TableHead>
              <TableHead>{t("setTable.columns.path")}</TableHead>
              <TableHead>{t("setTable.columns.language")}</TableHead>
              <TableHead>{t("setTable.columns.pairs")}</TableHead>
              <TableHead>{t("setTable.columns.status")}</TableHead>
              <TableHead>{t("setTable.columns.latestRun")}</TableHead>
              <TableHead>{t("setTable.columns.created")}</TableHead>
              {canDelete ? (
                <TableHead className="text-right">
                  {t("setTable.columns.actions")}
                </TableHead>
              ) : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.isLoading ? (
              <TableSkeleton columns={canDelete ? 8 : 7} />
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
                    {set.sourcePath ?? (
                      <span className="font-sans">{t("wholeProject")}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-sm">{ENDONYMS[set.language]}</TableCell>
                  <TableCell className="text-sm">{set.pairCount}</TableCell>
                  <TableCell>
                    <EvalStatusBadge status={set.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {set.latestRun
                      ? t("tally.summary", {
                          hits: set.latestRun.hits,
                          answered: set.latestRun.pairsAnswered,
                          correct: set.latestRun.correct,
                          partial: set.latestRun.partial,
                          wrong: set.latestRun.wrong,
                        })
                      : t("setTable.noRuns")}
                  </TableCell>
                  <TableCell
                    className="text-muted-foreground text-sm"
                    title={formatAbsolute(set.createdAt)}
                  >
                    {formatRelative(set.createdAt)}
                  </TableCell>
                  {canDelete ? (
                    <TableCell className="text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          render={
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label={t("setTable.actionsFor", { name: set.name })}
                            />
                          }
                        >
                          <MoreHorizontal className="size-4" />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onClick={() => setDeleting({ id: set.id, name: set.name })}
                          >
                            <Trash2 className="size-4" />
                            {t("setTable.delete")}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
      <PaginationFooter
        page={query.data?.page ?? page}
        totalPages={query.data?.totalPages ?? 1}
        totalCount={query.data?.totalCount ?? 0}
        onPageChange={setPage}
      />
      <DeleteEvalSetDialog
        projectId={projectId}
        set={deleting}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
      />
    </>
  );
}

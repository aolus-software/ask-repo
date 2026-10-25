"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";

import { ChecklistModuleStatusBadge } from "@/components/checklist/module-status-badge";
import { StalenessBadge } from "@/components/checklist/staleness-badge";
import { StatusBadge } from "@/components/feedback/status-badge";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ModuleRowActions } from "@/components/checklist/module-row-actions";
import type { ChecklistModuleResponse } from "@/lib/api/types";
import { formatAbsolute } from "@/lib/dates";
import {
  checklistItemResultTone,
  pendingChangeSetTone,
  toneTextClass,
} from "@/lib/status";
import { cn } from "@/lib/utils";
import { useFormatRelative } from "@/hooks/use-format-date";

/** Column order is fixed by `docs/design.md`: identity, status, timestamps, actions. */
export function ModuleTable({
  modules,
  isLoading,
}: {
  modules: ChecklistModuleResponse[];
  isLoading: boolean;
}) {
  const t = useTranslations("checklist.moduleTable");
  const formatRelative = useFormatRelative();
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("columns.module")}</TableHead>
            <TableHead>{t("columns.project")}</TableHead>
            <TableHead>{t("columns.status")}</TableHead>
            <TableHead>{t("columns.tests")}</TableHead>
            <TableHead>{t("columns.pass")}</TableHead>
            <TableHead>{t("columns.fail")}</TableHead>
            <TableHead>{t("columns.blocked")}</TableHead>
            <TableHead>{t("columns.untested")}</TableHead>
            <TableHead>{t("columns.lastGenerated")}</TableHead>
            <TableHead className="text-right">{t("columns.actions")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableSkeleton columns={10} />
          ) : (
            modules.map((module) => (
              <TableRow key={module.id}>
                <TableCell className="font-medium">
                  <Link href={`/checklist/${module.id}`} className="hover:text-primary">
                    {module.name}
                  </Link>
                  <div className="text-muted-foreground font-mono text-sm">
                    {module.sourcePath}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  <Link
                    href={`/projects/${module.projectId}`}
                    className="hover:text-primary"
                  >
                    {module.projectName}
                  </Link>
                </TableCell>
                <TableCell>
                  <div className="flex flex-col gap-2">
                    <ChecklistModuleStatusBadge status={module.status} />
                    {/* A second signal for the same fact as the status badge above —
                        it must agree with it, so it goes through the same tone the
                        `review` status uses rather than a hand-picked colour
                        (`docs/audit-finding-solved-logs.md` §U4.2). Kept distinct from the
                        status badge because a chat-originated change set can be
                        pending without the module's own status having moved to
                        `review`. */}
                    {module.pendingChangeSetId ? (
                      <StatusBadge
                        tone={pendingChangeSetTone()}
                        label={t("reviewChanges")}
                      />
                    ) : null}
                  </div>
                </TableCell>
                <TableCell className="text-sm">{module.itemCount}</TableCell>
                <TableCell className="text-sm">{module.passCount}</TableCell>
                <TableCell className="text-sm">
                  {module.status === "failed" && module.error ? (
                    <Tooltip>
                      <TooltipTrigger>
                        <div
                          className={cn(
                            toneTextClass(checklistItemResultTone("fail")),
                            "cursor-help truncate",
                          )}
                        >
                          {module.failCount}
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>{module.error}</TooltipContent>
                    </Tooltip>
                  ) : (
                    <span>{module.failCount}</span>
                  )}
                </TableCell>
                <TableCell className="text-sm">{module.blockedCount}</TableCell>
                <TableCell className="text-sm">{module.untestedCount}</TableCell>
                <TableCell
                  className="text-muted-foreground text-sm"
                  title={
                    module.lastGeneratedAt
                      ? formatAbsolute(module.lastGeneratedAt)
                      : undefined
                  }
                >
                  {module.lastGeneratedAt ? (
                    <>
                      {formatRelative(module.lastGeneratedAt)}
                      {module.stale ? (
                        <div className="mt-1">
                          <StalenessBadge />
                        </div>
                      ) : null}
                    </>
                  ) : (
                    "—"
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <ModuleRowActions module={module} />
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}

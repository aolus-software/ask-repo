"use client";

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
import { formatAbsolute, formatRelative } from "@/lib/dates";

/** Column order is fixed by `docs/design.md`: identity, status, timestamps, actions. */
export function ModuleTable({
  modules,
  isLoading,
}: {
  modules: ChecklistModuleResponse[];
  isLoading: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Module</TableHead>
            <TableHead>Project</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Tests</TableHead>
            <TableHead>Pass</TableHead>
            <TableHead>Fail</TableHead>
            <TableHead>Blocked</TableHead>
            <TableHead>Untested</TableHead>
            <TableHead>Last generated</TableHead>
            <TableHead className="text-right">Actions</TableHead>
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
                  <div className="text-muted-foreground text-sm">
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
                        (`docs/ui-audit-findings.md` §U4.2). Kept distinct from the
                        status badge because a chat-originated change set can be
                        pending without the module's own status having moved to
                        `review`. */}
                    {module.pendingChangeSetId ? (
                      <StatusBadge tone="warning" label="Review changes" />
                    ) : null}
                  </div>
                </TableCell>
                <TableCell className="text-sm">{module.itemCount}</TableCell>
                <TableCell className="text-sm">{module.passCount}</TableCell>
                <TableCell className="text-sm">
                  {module.status === "failed" && module.error ? (
                    <Tooltip>
                      <TooltipTrigger>
                        <div className="text-danger cursor-help truncate">
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

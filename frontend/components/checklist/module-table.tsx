"use client";

import Link from "next/link";

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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ModuleRowActions } from "@/components/checklist/module-row-actions";
import type { ChecklistModuleResponse, ChecklistModuleStatus } from "@/lib/api/types";
import { formatRelative } from "@/lib/dates";
import type { StatusTone } from "@/lib/status";

const STATUS_MAPPING: Record<ChecklistModuleStatus, string> = {
  empty: "Empty",
  generating: "Generating",
  review: "Review",
  ready: "Ready",
  failed: "Failed",
};

const STATUS_TONE_MAPPING: Record<ChecklistModuleStatus, StatusTone> = {
  empty: "neutral",
  generating: "warning",
  review: "warning",
  ready: "success",
  failed: "danger",
};

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
            <TableSkeleton columns={9} />
          ) : (
            modules.map((module) => (
              <TableRow key={module.id}>
                <TableCell className="font-medium">
                  <Link
                    href={`/checklist/${module.id}`}
                    className="hover:text-primary"
                  >
                    {module.name}
                  </Link>
                  <div className="text-muted-foreground text-sm">
                    {module.sourcePath}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-col gap-2">
                    <StatusBadge
                      tone={STATUS_TONE_MAPPING[module.status]}
                      label={STATUS_MAPPING[module.status] || module.status}
                    />
                    {module.pendingChangeSetId ? (
                      <div className="text-xs text-primary">Review changes</div>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell className="text-sm">{module.itemCount}</TableCell>
                <TableCell className="text-sm">{module.passCount}</TableCell>
                <TableCell className="text-sm">
                  {module.status === "failed" && module.error ? (
                    <Tooltip>
                      <TooltipTrigger>
                        <div className="text-destructive truncate cursor-help">
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
                <TableCell className="text-sm">
                  {module.untestedCount}
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
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

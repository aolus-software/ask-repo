"use client";

import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { StatusBadge } from "@/components/feedback/status-badge";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { PaginationFooter } from "@/components/layout/pagination-footer";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useActivity, useMemberships } from "@/hooks/use-profile";
import type { ActivityEntry, MembershipSummary } from "@/lib/api/types";
import { auditEventLabel } from "@/lib/audit";
import { formatAbsolute, formatRelative } from "@/lib/dates";

const PAGE_SIZE = 20;

/**
 * A conversation event always carries `targetLabel: null` — a conversation's title is
 * never stored on the audit row (`.claude/rules/audit-trail.md`) — so it is
 * identifiable only by `projectId`. Rendered as a link to the project when one is
 * known, named from the caller's own memberships when that project is among them,
 * and a bare "Project" label otherwise (a project the caller can still reach by id
 * but is not a member of, or was removed from since).
 */
function targetCell(
  item: ActivityEntry,
  memberships: MembershipSummary[] | undefined,
): React.ReactNode {
  if (item.targetLabel) return item.targetLabel;
  if (!item.projectId) return "—";
  const name = memberships?.find((m) => m.projectId === item.projectId)?.projectName;
  return (
    <Link
      href={`/projects/${item.projectId}`}
      className="text-primary underline-offset-4 hover:underline"
    >
      {name ?? "Project"}
    </Link>
  );
}

/**
 * Your own rows from the audit trail. A failed sign-in against your account appears
 * here with the address it came from — it is recorded with you as the actor.
 */
export function ActivitySection() {
  const [page, setPage] = useState(1);
  const activity = useActivity({ page, limit: PAGE_SIZE });
  const memberships = useMemberships();
  const items = activity.data?.items ?? [];

  return (
    <Card className="gap-4 p-6">
      {activity.isError ? (
        <ListError error={activity.error} onRetry={() => activity.refetch()} />
      ) : !activity.isLoading && items.length === 0 ? (
        <EmptyState size="compact" description="Nothing recorded yet." />
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Event</TableHead>
                <TableHead>Outcome</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>IP address</TableHead>
                <TableHead>Time</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {activity.isLoading ? (
                <TableSkeleton columns={5} />
              ) : (
                items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <StatusBadge
                        tone="neutral"
                        label={auditEventLabel(item.eventType)}
                      />
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        tone={item.outcome === "failure" ? "danger" : "success"}
                        label={item.outcome === "failure" ? "Failure" : "Success"}
                      />
                    </TableCell>
                    <TableCell className="text-sm">
                      {targetCell(item, memberships.data)}
                    </TableCell>
                    <TableCell className="text-sm">{item.ipAddress ?? "—"}</TableCell>
                    <TableCell
                      className="text-sm"
                      title={formatAbsolute(item.createdAt)}
                    >
                      {formatRelative(item.createdAt)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}
      {activity.data ? (
        <PaginationFooter
          page={activity.data.page}
          totalPages={activity.data.totalPages}
          totalCount={activity.data.totalCount}
          onPageChange={setPage}
        />
      ) : null}
    </Card>
  );
}

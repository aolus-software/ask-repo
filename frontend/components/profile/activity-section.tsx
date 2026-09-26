"use client";

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
import { useActivity } from "@/hooks/use-profile";
import { auditEventLabel } from "@/lib/audit";
import { formatAbsolute, formatRelative } from "@/lib/dates";

const PAGE_SIZE = 20;

/**
 * Your own rows from the audit trail. A failed sign-in against your account appears
 * here with the address it came from — it is recorded with you as the actor.
 */
export function ActivitySection() {
  const [page, setPage] = useState(1);
  const activity = useActivity({ page, limit: PAGE_SIZE });
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
                      <StatusBadge tone="neutral" label={auditEventLabel(item.eventType)} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        tone={item.outcome === "failure" ? "danger" : "success"}
                        label={item.outcome === "failure" ? "Failure" : "Success"}
                      />
                    </TableCell>
                    <TableCell className="text-sm">{item.targetLabel ?? "—"}</TableCell>
                    <TableCell className="text-sm">{item.ipAddress ?? "—"}</TableCell>
                    <TableCell className="text-sm" title={formatAbsolute(item.createdAt)}>
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

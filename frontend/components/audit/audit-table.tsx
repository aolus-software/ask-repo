"use client";

import Link from "next/link";

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
import { auditEventLabel } from "@/lib/audit";
import type { AuditEventSummary } from "@/lib/api/types";
import { formatAbsolute, formatRelative } from "@/lib/dates";

/** Column order: time, event, actor, target, outcome, changed fields. */
export function AuditTable({
  events,
  isLoading,
}: {
  events: AuditEventSummary[];
  isLoading: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Event</TableHead>
            <TableHead>Actor</TableHead>
            <TableHead>Target</TableHead>
            <TableHead>Outcome</TableHead>
            <TableHead>Changed</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableSkeleton columns={6} />
          ) : (
            events.map((event) => (
              <TableRow key={event.id}>
                <TableCell className="text-muted-foreground text-sm">
                  <Link
                    href={`/settings/audit/${event.id}`}
                    className="hover:text-primary"
                    title={formatAbsolute(event.createdAt)}
                  >
                    {formatRelative(event.createdAt)}
                  </Link>
                </TableCell>
                <TableCell>
                  <Link href={`/settings/audit/${event.id}`}>
                    <StatusBadge
                      tone="neutral"
                      label={auditEventLabel(event.eventType)}
                    />
                  </Link>
                </TableCell>
                <TableCell className="text-sm">
                  {event.actorEmail ?? (
                    <span
                      className="text-muted-foreground"
                      title="no authenticated actor"
                    >
                      —
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-sm">
                  {event.targetLabel ?? event.targetType ?? "—"}
                </TableCell>
                <TableCell>
                  <StatusBadge
                    tone={event.outcome === "failure" ? "danger" : "success"}
                    label={event.outcome === "failure" ? "Failure" : "Success"}
                  />
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {event.changedFields.length > 0
                    ? event.changedFields.join(", ")
                    : "—"}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}

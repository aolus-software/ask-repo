"use client";

import Link from "next/link";
import { useState } from "react";

import { AuditDetailDialog } from "@/components/audit/audit-detail-dialog";
import { StatusBadge } from "@/components/feedback/status-badge";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { Button } from "@/components/ui/button";
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

/** Column order: event, outcome, actor, target, changed fields, time, actions.
 *
 * Identity first, status second, timestamps last, actions right-aligned -- the same
 * order `/settings/users` and `/settings/roles` read in (`docs/design.md` -> Lists).
 * Time led here until `docs/ui-audit-findings.md` §U3.4; a trail is chronological, but
 * that is what the default sort expresses, not what the column order has to.
 */
export function AuditTable({
  events,
  isLoading,
}: {
  events: AuditEventSummary[];
  isLoading: boolean;
}) {
  // `null` closes the dialog and is what stops it fetching, so one piece of state
  // carries both which row is open and whether anything is open at all.
  const [openEventId, setOpenEventId] = useState<string | null>(null);

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Event</TableHead>
            <TableHead>Outcome</TableHead>
            <TableHead>Actor</TableHead>
            <TableHead>Target</TableHead>
            <TableHead>Changed</TableHead>
            <TableHead>Time</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableSkeleton columns={7} />
          ) : (
            events.map((event) => (
              <TableRow key={event.id}>
                <TableCell>
                  <Link href={`/settings/audit/${event.id}`}>
                    <StatusBadge
                      tone="neutral"
                      label={auditEventLabel(event.eventType)}
                    />
                  </Link>
                </TableCell>
                <TableCell>
                  <StatusBadge
                    tone={event.outcome === "failure" ? "danger" : "success"}
                    label={event.outcome === "failure" ? "Failure" : "Success"}
                  />
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
                <TableCell className="text-muted-foreground text-sm">
                  {event.changedFields.length > 0
                    ? event.changedFields.join(", ")
                    : "—"}
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  <Link
                    href={`/settings/audit/${event.id}`}
                    className="hover:text-primary"
                    title={formatAbsolute(event.createdAt)}
                  >
                    {formatRelative(event.createdAt)}
                  </Link>
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setOpenEventId(event.id)}
                  >
                    View
                  </Button>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      <AuditDetailDialog
        eventId={openEventId}
        onOpenChange={(open) => {
          if (!open) setOpenEventId(null);
        }}
      />
    </div>
  );
}

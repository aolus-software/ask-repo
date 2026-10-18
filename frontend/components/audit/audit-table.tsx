"use client";

import { useTranslations } from "next-intl";
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
import { useAuditEventLabel } from "@/lib/audit";
import { auditOutcomeLabelKey, auditOutcomeTone } from "@/lib/status";
import type { AuditEventSummary } from "@/lib/api/types";
import { formatAbsolute } from "@/lib/dates";
import { useFormatRelative } from "@/hooks/use-format-date";

/** Column order: event, outcome, actor, target, changed fields, time, actions.
 *
 * Identity first, status second, timestamps last, actions right-aligned -- the same
 * order `/settings/users` and `/settings/roles` read in (`docs/design.md` -> Lists).
 * Time led here until `docs/audit-finding-solved-logs.md` §U3.4; a trail is chronological, but
 * that is what the default sort expresses, not what the column order has to.
 */
export function AuditTable({
  events,
  isLoading,
}: {
  events: AuditEventSummary[];
  isLoading: boolean;
}) {
  const t = useTranslations("audit.table");
  const tStatus = useTranslations("status");
  const auditEventLabel = useAuditEventLabel();
  const formatRelative = useFormatRelative();
  // `null` closes the dialog and is what stops it fetching, so one piece of state
  // carries both which row is open and whether anything is open at all.
  const [openEventId, setOpenEventId] = useState<string | null>(null);

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("columns.event")}</TableHead>
            <TableHead>{t("columns.outcome")}</TableHead>
            <TableHead>{t("columns.actor")}</TableHead>
            <TableHead>{t("columns.target")}</TableHead>
            <TableHead>{t("columns.changed")}</TableHead>
            <TableHead>{t("columns.time")}</TableHead>
            <TableHead className="text-right">{t("columns.actions")}</TableHead>
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
                    tone={auditOutcomeTone(event.outcome)}
                    label={tStatus(auditOutcomeLabelKey(event.outcome))}
                  />
                </TableCell>
                <TableCell className="text-sm">
                  {event.actorEmail ?? (
                    <span className="text-muted-foreground" title={t("noActor")}>
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
                    {t("view")}
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

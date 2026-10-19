"use client";

import { useTranslations } from "next-intl";

import {
  AuditEventCurrent,
  AuditEventFacts,
} from "@/components/audit/audit-event-detail";
import { DetailError } from "@/components/feedback/detail-error";
import { StatusBadge } from "@/components/feedback/status-badge";
import { SIZES } from "@/components/form/form-dialog";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuditEvent } from "@/hooks/use-audit-events";
import { useAuditEventLabel } from "@/lib/audit";
import { auditOutcomeLabelKey, auditOutcomeTone } from "@/lib/status";
import { useFormatRelative } from "@/hooks/use-format-date";

/**
 * One event, read without leaving the list.
 *
 * The `/settings/audit/[eventId]` route still exists and is still the thing a link
 * points at — an operator citing a row in a ticket needs a URL, and a dialog has
 * none. This is the quick look that keeps the filters and the scroll position.
 *
 * `eventId` is `null` when closed, and `useAuditEvent` is already guarded on a falsy
 * id, so nothing is fetched until a row is actually opened.
 */
export function AuditDetailDialog({
  eventId,
  onOpenChange,
}: {
  eventId: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("audit.detail");
  const tStatus = useTranslations("status");
  const auditEventLabel = useAuditEventLabel();
  const formatRelative = useFormatRelative();
  const query = useAuditEvent(eventId ?? "");
  const event = query.data;

  return (
    <Dialog open={eventId !== null} onOpenChange={onOpenChange}>
      <DialogContent className={SIZES.lg}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {event ? auditEventLabel(event.eventType) : t("dialogTitle")}
            {event ? (
              <StatusBadge
                tone={auditOutcomeTone(event.outcome)}
                label={tStatus(auditOutcomeLabelKey(event.outcome))}
              />
            ) : null}
          </DialogTitle>
          <DialogDescription>
            {event
              ? t("recorded", { time: formatRelative(event.createdAt) })
              : t("dialogLoading")}
          </DialogDescription>
        </DialogHeader>

        {/* The trail can run to a long `changed` block and a long context block, so
            the body scrolls rather than pushing the dialog past the viewport. */}
        <div className="max-h-[70vh] overflow-y-auto">
          {query.isLoading ? (
            <div className="space-y-4">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : query.error ? (
            <DetailError
              error={query.error}
              notFoundMessage={t("notFound")}
              onRetry={() => query.refetch()}
            />
          ) : event ? (
            <div className="space-y-6">
              <AuditEventFacts event={event} />
              {/* The real `Card`, not a Card-shaped div: a hand-copied radius and
                  border stop tracking the token the moment `Card` is restyled
                  (`docs/audit-finding-solved-logs.md` §U2.4). */}
              <Card className="border-info/40 bg-info/5 p-6">
                <AuditEventCurrent event={event} />
              </Card>
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

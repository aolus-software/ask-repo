"use client";

import {
  AuditEventCurrent,
  AuditEventFacts,
} from "@/components/audit/audit-event-detail";
import { DetailError } from "@/components/feedback/detail-error";
import { StatusBadge } from "@/components/feedback/status-badge";
import { SIZES } from "@/components/form/form-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuditEvent } from "@/hooks/use-audit-events";
import { auditEventLabel } from "@/lib/audit";
import { formatRelative } from "@/lib/dates";

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
  const query = useAuditEvent(eventId ?? "");
  const event = query.data;

  return (
    <Dialog open={eventId !== null} onOpenChange={onOpenChange}>
      <DialogContent className={SIZES.lg}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {event ? auditEventLabel(event.eventType) : "Audit event"}
            {event ? (
              <StatusBadge
                tone={event.outcome === "failure" ? "danger" : "success"}
                label={event.outcome === "failure" ? "Failure" : "Success"}
              />
            ) : null}
          </DialogTitle>
          <DialogDescription>
            {event
              ? `Recorded ${formatRelative(event.createdAt)}`
              : "Reading the recorded event."}
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
              notFoundMessage="That event does not exist, or has aged out of the retention window."
              onRetry={() => query.refetch()}
            />
          ) : event ? (
            <div className="space-y-6">
              <AuditEventFacts event={event} />
              <div className="border-info/40 bg-info/5 rounded-xl border p-4">
                <AuditEventCurrent event={event} />
              </div>
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

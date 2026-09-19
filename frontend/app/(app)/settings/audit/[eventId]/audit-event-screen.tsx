"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import {
  AuditEventCurrent,
  AuditEventFacts,
} from "@/components/audit/audit-event-detail";
import { DetailError } from "@/components/feedback/detail-error";
import { Forbidden } from "@/components/feedback/forbidden";
import { NotFound } from "@/components/feedback/not-found";
import { StatusBadge } from "@/components/feedback/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuditEvent } from "@/hooks/use-audit-events";
import { useSession } from "@/hooks/use-session";
import { auditEventLabel } from "@/lib/audit";
import { formatRelative } from "@/lib/dates";

export function AuditEventScreen({ id }: { id: string }) {
  const user = useSession();
  const query = useAuditEvent(id);

  // The route body is wrapped in its gate. Hiding the nav item is not gating the
  // route — an operator can type the URL (navigation.md §6). This mirrors the
  // backend's admin-only dependency; it does not replace it.
  if (!user.isAdmin)
    return <Forbidden message="Only administrators can read the audit trail." />;

  if (query.isLoading) {
    return (
      <div className="mx-auto w-full max-w-3xl space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (query.error) {
    return (
      <div className="mx-auto w-full max-w-3xl">
        <DetailError
          error={query.error}
          notFoundMessage="That event does not exist, or has aged out of the retention window."
          onRetry={() => query.refetch()}
        />
      </div>
    );
  }

  const event = query.data;
  if (!event) return <NotFound />;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <PageHeader
        title={auditEventLabel(event.eventType)}
        titleAddon={
          <StatusBadge
            tone={event.outcome === "failure" ? "danger" : "success"}
            label={event.outcome === "failure" ? "Failure" : "Success"}
          />
        }
        description={`Recorded ${formatRelative(event.createdAt)}`}
        action={
          <Button
            variant="outline"
            size="sm"
            nativeButton={false}
            render={<Link href="/settings/audit" />}
          >
            <ArrowLeft className="size-4" />
            Back to audit trail
          </Button>
        }
      />

      <Card className="p-6">
        <AuditEventFacts event={event} />
      </Card>

      {/* Live lookups, fenced off in their own group and labelled as a present-tense
          answer — never part of the recorded snapshot above (audit-trail.md). */}
      <Card className="border-info/40 bg-info/5 p-6">
        <AuditEventCurrent event={event} />
      </Card>
    </div>
  );
}

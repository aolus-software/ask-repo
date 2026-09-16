"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import {
  AuditChangeList,
  type AuditChange,
} from "@/components/audit/audit-change-list";
import { DetailError } from "@/components/feedback/detail-error";
import { Forbidden } from "@/components/feedback/forbidden";
import { NotFound } from "@/components/feedback/not-found";
import { StatusBadge } from "@/components/feedback/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuditEvent } from "@/hooks/use-audit-events";
import { useSession } from "@/hooks/use-session";
import { auditEventLabel } from "@/lib/audit";
import { formatAbsolute, formatRelative } from "@/lib/dates";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <dt className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
        {label}
      </dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function tristate(value: boolean | null, whenTrue: string, whenFalse: string): string {
  if (value === null) return "Unknown";
  return value ? whenTrue : whenFalse;
}

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

  // `changed` and the rest of `details` come from the same free-form object; the
  // change list owns the former, the context block below owns whatever is left.
  const { changed, ...context } = event.details as {
    changed?: Record<string, AuditChange>;
  } & Record<string, unknown>;
  const contextEntries = Object.entries(context);

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
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="When">{formatAbsolute(event.createdAt)}</Field>
          <Field label="Who">
            {event.actorEmail ?? (
              <span className="text-muted-foreground">no authenticated actor</span>
            )}
          </Field>
          <Field label="What">{auditEventLabel(event.eventType)}</Field>
          <Field label="Target">
            {event.targetLabel ?? event.targetType ?? (
              <span className="text-muted-foreground">—</span>
            )}
          </Field>
          <Field label="Project">
            {event.projectId ?? <span className="text-muted-foreground">—</span>}
          </Field>
          <Field label="Outcome">
            {event.outcome === "failure" ? "Failure" : "Success"}
          </Field>
          <Field label="Source IP">
            {event.ipAddress ?? <span className="text-muted-foreground">—</span>}
          </Field>
        </dl>

        <Separator className="my-6" />

        <div>
          <h2 className="mb-3 text-sm font-semibold">Changed fields</h2>
          {changed && Object.keys(changed).length > 0 ? (
            <AuditChangeList changed={changed} />
          ) : (
            <p className="text-muted-foreground text-sm">
              This event has no `changed` block — its name is its whole meaning.
            </p>
          )}
        </div>

        {contextEntries.length > 0 ? (
          <>
            <Separator className="my-6" />
            <div>
              <h2 className="mb-3 text-sm font-semibold">Context</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {contextEntries.map(([key, value]) => (
                  <Field key={key} label={key}>
                    {typeof value === "boolean" ? String(value) : String(value ?? "—")}
                  </Field>
                ))}
              </dl>
            </div>
          </>
        ) : null}
      </Card>

      {/* Live lookups, fenced off in their own group and labelled as a present-tense
          answer — never part of the recorded snapshot above (audit-trail.md). */}
      <Card className="border-info/40 bg-info/5 p-6">
        <h2 className="text-muted-foreground mb-3 text-xs font-medium tracking-wide uppercase">
          As of now
        </h2>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Actor still active">
            {tristate(event.current.actorStillActive, "Yes", "No")}
          </Field>
          <Field label="Target still exists">
            {tristate(event.current.targetStillExists, "Yes", "No")}
          </Field>
        </dl>
      </Card>
    </div>
  );
}

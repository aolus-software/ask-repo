"use client";

import {
  AuditChangeList,
  AuditValue,
  type AuditChange,
} from "@/components/audit/audit-change-list";
import { Separator } from "@/components/ui/separator";
import { auditEventLabel } from "@/lib/audit";
import type { AuditEventResponse } from "@/lib/api/types";
import { formatAbsolute } from "@/lib/dates";

/**
 * One recorded event's body, with no surface of its own.
 *
 * Two screens render this: the `/settings/audit/[eventId]` route and the dialog the
 * table opens. Neither owns it, deliberately -- a second copy would drift, and the
 * drift would be invisible, since nothing fails when one of them stops showing a
 * field the other shows. The wrapper is the caller's: the route puts these in Cards,
 * the dialog stacks them directly.
 */

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

/** The recorded snapshot: who, what, when, and whatever `details` carried. */
export function AuditEventFacts({ event }: { event: AuditEventResponse }) {
  // `changed` and the rest of `details` come from the same free-form object; the
  // change list owns the former, the context block below owns whatever is left.
  const { changed, ...context } = event.details as {
    changed?: Record<string, AuditChange>;
  } & Record<string, unknown>;
  const contextEntries = Object.entries(context);

  return (
    <>
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
          {/* An identifier, so mono: an operator reads this to match it against another
              system, and the body face does not separate 0 from O or 1 from l. */}
          {event.projectId ? (
            <span className="font-mono">{event.projectId}</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
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
                  <AuditValue value={value} />
                </Field>
              ))}
            </dl>
          </div>
        </>
      ) : null}
    </>
  );
}

/**
 * Live lookups, kept in their own labelled group and never mixed into the snapshot
 * above (`.claude/rules/audit-trail.md`) — a present-tense answer must not read as
 * part of what was recorded.
 */
export function AuditEventCurrent({ event }: { event: AuditEventResponse }) {
  return (
    <>
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
    </>
  );
}

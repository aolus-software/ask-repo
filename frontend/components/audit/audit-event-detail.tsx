"use client";

import { useTranslations } from "next-intl";

import {
  AuditChangeList,
  AuditValue,
  type AuditChange,
} from "@/components/audit/audit-change-list";
import { Separator } from "@/components/ui/separator";
import { useAuditEventLabel } from "@/lib/audit";
import type { AuditEventResponse } from "@/lib/api/types";
import { formatAbsolute } from "@/lib/dates";
import { auditOutcomeLabelKey } from "@/lib/status";

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

/** The recorded snapshot: who, what, when, and whatever `details` carried. */
export function AuditEventFacts({ event }: { event: AuditEventResponse }) {
  const t = useTranslations("audit.detail");
  const tStatus = useTranslations("status");
  const auditEventLabel = useAuditEventLabel();
  // `changed` and the rest of `details` come from the same free-form object; the
  // change list owns the former, the context block below owns whatever is left.
  const { changed, ...context } = event.details as {
    changed?: Record<string, AuditChange>;
  } & Record<string, unknown>;
  const contextEntries = Object.entries(context);

  return (
    <>
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label={t("when")}>{formatAbsolute(event.createdAt)}</Field>
        <Field label={t("who")}>
          {event.actorEmail ?? (
            <span className="text-muted-foreground">{t("noActor")}</span>
          )}
        </Field>
        <Field label={t("what")}>{auditEventLabel(event.eventType)}</Field>
        <Field label={t("target")}>
          {event.targetLabel ?? event.targetType ?? (
            <span className="text-muted-foreground">—</span>
          )}
        </Field>
        <Field label={t("project")}>
          {/* An identifier, so mono: an operator reads this to match it against another
              system, and the body face does not separate 0 from O or 1 from l. */}
          {event.projectId ? (
            <span className="font-mono">{event.projectId}</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </Field>
        <Field label={t("outcome")}>
          {tStatus(auditOutcomeLabelKey(event.outcome))}
        </Field>
        <Field label={t("sourceIp")}>
          {event.ipAddress ? (
            <span className="font-mono">{event.ipAddress}</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </Field>
      </dl>

      <Separator className="my-6" />

      <div>
        <h2 className="mb-3 text-sm font-semibold">{t("changedFields")}</h2>
        {changed && Object.keys(changed).length > 0 ? (
          <AuditChangeList changed={changed} />
        ) : (
          <p className="text-muted-foreground text-sm">{t("noChangedBlock")}</p>
        )}
      </div>

      {contextEntries.length > 0 ? (
        <>
          <Separator className="my-6" />
          <div>
            <h2 className="mb-3 text-sm font-semibold">{t("context")}</h2>
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
  const t = useTranslations("audit.detail");
  const tristate = (value: boolean | null): string =>
    value === null ? t("unknown") : value ? t("yes") : t("no");
  return (
    <>
      <h2 className="text-muted-foreground mb-3 text-xs font-medium tracking-wide uppercase">
        {t("asOfNow")}
      </h2>
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label={t("actorStillActive")}>
          {tristate(event.current.actorStillActive)}
        </Field>
        <Field label={t("targetStillExists")}>
          {tristate(event.current.targetStillExists)}
        </Field>
      </dl>
    </>
  );
}

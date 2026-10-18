"use client";

import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { useAuditFieldLabel } from "@/lib/audit";

/** One field's before/after pair, exactly as `AuditEventResponse.details.changed`
 * carries it on the wire — `before`/`after` is `null` on the side a create or a
 * delete has nothing for, a plain scalar on an update, or a list for something like
 * a permission set. */
export interface AuditChange {
  before: unknown;
  after: unknown;
}

/**
 * Renders any value this app's audit payloads can carry: `null`/`undefined` as a
 * muted em dash, a list as its items (never a joined string — `getByText`, and a
 * human skimming a permission diff, needs to find one item, not a substring of a
 * sentence), a plain object as structured JSON, and everything else as a string.
 *
 * Shared between the before/after pairs in `AuditChangeList` and the flat context
 * block on the event detail screen (`audit-event-screen.tsx`) — both read from the
 * same free-form `details` payload, and a `results_cleared` or `checklist.exported`
 * event carries a `filter` object in its context describing exactly what was
 * selected. Duplicating this per call site is how the two rendering paths drifted:
 * the context block fell back to `String(value)`, which prints `[object Object]`
 * for exactly that filter.
 */
export function AuditValue({ value }: { value: unknown }) {
  const t = useTranslations("audit.changes");
  if (value === null || value === undefined) {
    return (
      <span className="text-muted-foreground italic" aria-label={t("none")}>
        —
      </span>
    );
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-muted-foreground italic">{t("empty")}</span>;
    }
    return (
      <div className="flex flex-wrap gap-1">
        {value.map((item, index) => (
          <Badge key={index} variant="outline" className="font-normal">
            {String(item)}
          </Badge>
        ))}
      </div>
    );
  }

  if (typeof value === "object") {
    return (
      <pre className="bg-muted overflow-x-auto rounded-md p-2 text-xs">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  return <span>{String(value)}</span>;
}

/**
 * Renders every entry in `changed` as a before -> after pair. One renderer handles
 * all three shapes a write can produce (`.claude/rules/audit-trail.md`):
 *
 * - create: `before` is `null` — the em dash on the left, the new value on the right.
 * - delete: `after` is `null` — the old value on the left, the em dash on the right.
 * - update: both sides carry a value.
 *
 * The absent side is always the muted em dash, never the literal string "null" —
 * printing "null" would make a normal create or delete read as a bug.
 */
export function AuditChangeList({ changed }: { changed: Record<string, AuditChange> }) {
  const t = useTranslations("audit.changes");
  const fieldLabel = useAuditFieldLabel();
  const entries = Object.entries(changed);

  if (entries.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("noFields")}</p>;
  }

  return (
    <dl className="divide-border divide-y">
      {entries.map(([field, { before, after }]) => (
        <div key={field} className="flex flex-col gap-1.5 py-2.5 first:pt-0 last:pb-0">
          <dt className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            {fieldLabel(field)}
          </dt>
          <dd className="flex flex-wrap items-center gap-2 text-sm">
            <AuditValue value={before} />
            <ArrowRight className="text-muted-foreground size-4 shrink-0" />
            <AuditValue value={after} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

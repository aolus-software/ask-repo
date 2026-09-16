import { ArrowRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";

/** One field's before/after pair, exactly as `AuditEventResponse.details.changed`
 * carries it on the wire — `before`/`after` is `null` on the side a create or a
 * delete has nothing for, a plain scalar on an update, or a list for something like
 * a permission set. */
export interface AuditChange {
  before: unknown;
  after: unknown;
}

/** "isAdmin" -> "Is admin", "email" -> "Email". Derived from the key rather than a
 * lookup table, so a new allowlisted field never needs a matching label added here. */
function humanizeField(key: string): string {
  const spaced = key.replace(/([A-Z])/g, " $1").trim();
  const lower = spaced.toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

/** A list renders as its items, never as a joined string — `getByText` (and a human
 * skimming a permission diff) needs to find one item, not a substring of a sentence. */
function ChangeValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return (
      <span className="text-muted-foreground italic" aria-label="none">
        —
      </span>
    );
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-muted-foreground italic">empty</span>;
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
export function AuditChangeList({
  changed,
}: {
  changed: Record<string, AuditChange>;
}) {
  const entries = Object.entries(changed);

  if (entries.length === 0) {
    return <p className="text-muted-foreground text-sm">No fields recorded.</p>;
  }

  return (
    <dl className="divide-border divide-y">
      {entries.map(([field, { before, after }]) => (
        <div key={field} className="flex flex-col gap-1.5 py-2.5 first:pt-0 last:pb-0">
          <dt className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            {humanizeField(field)}
          </dt>
          <dd className="flex flex-wrap items-center gap-2 text-sm">
            <ChangeValue value={before} />
            <ArrowRight className="text-muted-foreground size-3.5 shrink-0" />
            <ChangeValue value={after} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

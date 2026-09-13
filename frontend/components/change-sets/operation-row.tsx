"use client";

import { Checkbox } from "@/components/ui/checkbox";

/**
 * One row in a change-set review list: a checkbox, dimmed when its target has
 * already left the underlying collection. Shared between the checklist and
 * mock-data change-set panels (`docs/ui-audit-findings.md` §U8.3) — both review an
 * `add`/`update`/`remove` proposal list against a resource that may have moved out
 * from under it since the proposal was generated, and a reviewer who has learned to
 * read one should not have to relearn the other.
 */
export function OperationRow({
  checked,
  onToggle,
  orphaned,
  children,
}: {
  checked: boolean;
  onToggle: () => void;
  orphaned: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 py-3">
      <Checkbox
        checked={checked}
        onCheckedChange={onToggle}
        className="mt-1"
        aria-label="Include this change"
      />
      <div className={orphaned ? "text-muted-foreground flex-1" : "flex-1"}>
        {children}
      </div>
    </div>
  );
}

/** The rationale line under every operation, with the same "none given" fallback. */
export function OperationRationale({ rationale }: { rationale: string }) {
  return (
    <p className="text-muted-foreground text-sm">
      {rationale.trim() ? rationale : "No rationale given."}
    </p>
  );
}

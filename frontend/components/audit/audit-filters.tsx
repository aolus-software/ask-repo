"use client";

import { AUDIT_EVENT_TYPES, auditEventLabel } from "@/lib/audit";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AuditEventListParams, AuditOutcome } from "@/lib/api/types";

/**
 * "No filter" needs a real option value. An empty string is not one: a select whose
 * item value is `""` is indistinguishable from an unset select, and the libraries this
 * component is built on treat the two differently. The sentinel never leaves this file
 * -- it is mapped back to `undefined` before the params are serialised.
 */
const ANY = "any";

const OUTCOME_LABELS: Record<AuditOutcome, string> = {
  success: "Success",
  failure: "Failure",
};

export function AuditFilters({
  currentFilters,
  onFiltersChange,
}: {
  currentFilters: Partial<AuditEventListParams>;
  onFiltersChange: (filters: Partial<AuditEventListParams>) => void;
}) {
  return (
    // The same grid `ListToolbar` uses for its own filter row (`docs/design.md` →
    // Spacing). Rendered directly by the screen, so the row is declared here.
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
      <div>
        <Select
          value={currentFilters.eventType ?? ANY}
          onValueChange={(value) =>
            onFiltersChange({
              ...currentFilters,
              eventType: value === ANY || value === null ? undefined : value,
            })
          }
        >
          <SelectTrigger className="w-full">
            {/* Base UI renders the raw selected value, not the item's label, so
                without this the trigger reads "any" or "project.deleted" instead of
                the wording in the menu. */}
            <SelectValue>
              {(value: string) => (value === ANY ? "All events" : auditEventLabel(value))}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>All events</SelectItem>
            {AUDIT_EVENT_TYPES.map((eventType) => (
              <SelectItem key={eventType} value={eventType}>
                {auditEventLabel(eventType)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Select
          value={currentFilters.outcome ?? ANY}
          onValueChange={(value) =>
            onFiltersChange({
              ...currentFilters,
              outcome: value === ANY ? undefined : (value as AuditOutcome),
            })
          }
        >
          <SelectTrigger className="w-full">
            <SelectValue>
              {(value: string) =>
                value === ANY ? "All outcomes" : OUTCOME_LABELS[value as AuditOutcome]
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>All outcomes</SelectItem>
            {Object.entries(OUTCOME_LABELS).map(([key, label]) => (
              <SelectItem key={key} value={key}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Input
          type="date"
          value={currentFilters.occurredFrom?.slice(0, 10) ?? ""}
          onChange={(event) =>
            onFiltersChange({
              ...currentFilters,
              occurredFrom: event.target.value || undefined,
            })
          }
          aria-label="From date"
        />
      </div>

      <div>
        <Input
          type="date"
          value={currentFilters.occurredTo?.slice(0, 10) ?? ""}
          onChange={(event) =>
            onFiltersChange({
              ...currentFilters,
              occurredTo: event.target.value || undefined,
            })
          }
          aria-label="To date"
        />
      </div>
    </div>
  );
}

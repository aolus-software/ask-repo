"use client";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  ChecklistItemKind,
  ChecklistItemListParams,
  ChecklistItemSource,
  ChecklistItemStatus,
} from "@/lib/api/types";

/**
 * "No filter" needs a real option value. An empty string is not one: a select whose
 * item value is `""` is indistinguishable from an unset select, and the libraries this
 * component is built on treat the two differently. The sentinel never leaves this file
 * -- it is mapped back to `undefined` before the params are serialised.
 */
const ANY = "any";

const STATUS_LABELS: Record<ChecklistItemStatus, string> = {
  untested: "Untested",
  pass: "Pass",
  fail: "Fail",
  blocked: "Blocked",
};

const SOURCE_LABELS: Record<ChecklistItemSource, string> = {
  generated: "Generated",
  manual: "Manual",
};

const KIND_LABELS: Record<ChecklistItemKind, string> = {
  positive: "Positive",
  negative: "Negative",
};

export function ItemFilters({
  currentFilters,
  onFiltersChange,
}: {
  currentFilters: Partial<ChecklistItemListParams>;
  onFiltersChange: (filters: Partial<ChecklistItemListParams>) => void;
}) {
  return (
    // One row, not four stacked full-width controls. Unlike `ListToolbar`'s filters
    // slot these are rendered directly by the screen, so the row has to be declared
    // here or each child becomes its own block.
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <div>
        <Input
          placeholder="Filter by feature"
          value={currentFilters.feature ?? ""}
          onChange={(event) =>
            onFiltersChange({
              ...currentFilters,
              feature: event.target.value || undefined,
            })
          }
          aria-label="Filter by feature"
        />
      </div>

      <div>
        <Select
          value={currentFilters.status ?? ANY}
          onValueChange={(value) =>
            onFiltersChange({
              ...currentFilters,
              status: value === ANY ? undefined : (value as ChecklistItemStatus),
            })
          }
        >
          <SelectTrigger className="w-full">
            {/* Base UI renders the raw selected value, not the item's label, so
                without this the trigger reads "any" or "pass" instead of the
                wording in the menu. */}
            <SelectValue>
              {(value: string) =>
                value === ANY
                  ? "All statuses"
                  : STATUS_LABELS[value as ChecklistItemStatus]
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>All statuses</SelectItem>
            {Object.entries(STATUS_LABELS).map(([key, label]) => (
              <SelectItem key={key} value={key}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        {/* The filter this whole field exists for: "show me the failure coverage". */}
        <Select
          value={currentFilters.kind ?? ANY}
          onValueChange={(value) =>
            onFiltersChange({
              ...currentFilters,
              kind: value === ANY ? undefined : (value as ChecklistItemKind),
            })
          }
        >
          <SelectTrigger className="w-full">
            <SelectValue>
              {(value: string) =>
                value === ANY ? "All kinds" : KIND_LABELS[value as ChecklistItemKind]
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>All kinds</SelectItem>
            {Object.entries(KIND_LABELS).map(([key, label]) => (
              <SelectItem key={key} value={key}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Select
          value={currentFilters.source ?? ANY}
          onValueChange={(value) =>
            onFiltersChange({
              ...currentFilters,
              source: value === ANY ? undefined : (value as ChecklistItemSource),
            })
          }
        >
          <SelectTrigger className="w-full">
            {/* Base UI renders the raw selected value, not the item's label, so
                without this the trigger reads "any" or "pass" instead of the
                wording in the menu. */}
            <SelectValue>
              {(value: string) =>
                value === ANY
                  ? "All sources"
                  : SOURCE_LABELS[value as ChecklistItemSource]
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>All sources</SelectItem>
            {Object.entries(SOURCE_LABELS).map(([key, label]) => (
              <SelectItem key={key} value={key}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

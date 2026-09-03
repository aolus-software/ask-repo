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

export function ItemFilters({
  currentFilters,
  onFiltersChange,
}: {
  currentFilters: Partial<ChecklistItemListParams>;
  onFiltersChange: (filters: Partial<ChecklistItemListParams>) => void;
}) {
  return (
    <>
      <div>
        <Input
          placeholder="Filter by feature"
          value={currentFilters.feature ?? ""}
          onChange={(event) =>
            onFiltersChange({ ...currentFilters, feature: event.target.value || undefined })
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
          <SelectTrigger>
            <SelectValue placeholder="All statuses" />
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
        <Select
          value={currentFilters.source ?? ANY}
          onValueChange={(value) =>
            onFiltersChange({
              ...currentFilters,
              source: value === ANY ? undefined : (value as ChecklistItemSource),
            })
          }
        >
          <SelectTrigger>
            <SelectValue placeholder="All sources" />
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
    </>
  );
}

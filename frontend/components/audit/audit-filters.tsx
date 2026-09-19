"use client";

import { useMemo } from "react";

import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { AUDIT_EVENT_TYPES, auditEventLabel } from "@/lib/audit";
import type { AuditEventListParams, AuditOutcome } from "@/lib/api/types";

/**
 * "No filter" needs a real option value. An empty string is not one: a control whose
 * item value is `""` is indistinguishable from an unset one, and the libraries this
 * component is built on treat the two differently. The sentinel never leaves this file
 * -- it is mapped back to `undefined` before the params are serialised.
 */
const ANY = "any";

/**
 * The combobox matches on the *object*, not on a string, so an option has to be a
 * stable value both the list and the current selection can point at.
 */
type FilterOption = { value: string; label: string };

const OUTCOME_OPTIONS: FilterOption[] = [
  { value: ANY, label: "All outcomes" },
  { value: "success", label: "Success" },
  { value: "failure", label: "Failure" },
];

export function AuditFilters({
  currentFilters,
  onFiltersChange,
}: {
  currentFilters: Partial<AuditEventListParams>;
  onFiltersChange: (filters: Partial<AuditEventListParams>) => void;
}) {
  // 37 event types is past the point where a plain select is usable -- finding
  // `checklist_item.results_cleared` means scrolling a menu that does not narrow.
  // A combobox filters as you type, which is what makes the list a tool rather than
  // an inventory.
  const eventOptions = useMemo<FilterOption[]>(
    () => [
      { value: ANY, label: "All events" },
      ...AUDIT_EVENT_TYPES.map((eventType) => ({
        value: eventType,
        label: auditEventLabel(eventType),
      })),
    ],
    [],
  );

  const selectedEvent =
    eventOptions.find((option) => option.value === (currentFilters.eventType ?? ANY)) ??
    eventOptions[0];

  const selectedOutcome =
    OUTCOME_OPTIONS.find(
      (option) => option.value === (currentFilters.outcome ?? ANY),
    ) ?? OUTCOME_OPTIONS[0];

  return (
    // A fragment, not a grid: these are dropped into `ListToolbar`'s own filter row
    // (`docs/design.md` -> Spacing), so each control has to be a direct child of that
    // grid to get a cell of its own. Wrapping them in a nested grid here puts all four
    // inside a single cell, which collapses every control to a quarter of one column --
    // wide enough for "All e..." and a clipped date picker.
    <>
      <div>
        <Combobox
          items={eventOptions}
          value={selectedEvent}
          onValueChange={(next: FilterOption | null) =>
            onFiltersChange({
              ...currentFilters,
              eventType: !next || next.value === ANY ? undefined : next.value,
            })
          }
          itemToStringLabel={(option: FilterOption) => option.label}
        >
          <ComboboxInput
            className="w-full"
            placeholder="All events"
            aria-label="Event type"
          />
          <ComboboxContent>
            <ComboboxEmpty>No event type matches.</ComboboxEmpty>
            <ComboboxList>
              {(option: FilterOption) => (
                <ComboboxItem key={option.value} value={option}>
                  {option.label}
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
      </div>

      <div>
        <Combobox
          items={OUTCOME_OPTIONS}
          value={selectedOutcome}
          onValueChange={(next: FilterOption | null) =>
            onFiltersChange({
              ...currentFilters,
              outcome:
                !next || next.value === ANY ? undefined : (next.value as AuditOutcome),
            })
          }
          itemToStringLabel={(option: FilterOption) => option.label}
        >
          <ComboboxInput
            className="w-full"
            placeholder="All outcomes"
            aria-label="Outcome"
          />
          <ComboboxContent>
            <ComboboxEmpty>No outcome matches.</ComboboxEmpty>
            <ComboboxList>
              {(option: FilterOption) => (
                <ComboboxItem key={option.value} value={option}>
                  {option.label}
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
      </div>

      <div>
        <Input
          type="date"
          className="w-full"
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
          className="w-full"
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
    </>
  );
}

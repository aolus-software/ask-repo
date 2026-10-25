"use client";

import { useTranslations } from "next-intl";

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

// Only the codes live here; the words are `checklist.itemFilters.*`, translated at render.
const STATUSES: ChecklistItemStatus[] = ["untested", "pass", "fail", "blocked"];
const SOURCES: ChecklistItemSource[] = ["generated", "manual"];
const KINDS: ChecklistItemKind[] = ["positive", "negative"];

export function ItemFilters({
  currentFilters,
  onFiltersChange,
}: {
  currentFilters: Partial<ChecklistItemListParams>;
  onFiltersChange: (filters: Partial<ChecklistItemListParams>) => void;
}) {
  const t = useTranslations("checklist");
  return (
    // The same grid `ListToolbar` uses for its own filter row
    // (`docs/design.md` → Spacing): one row, not four stacked full-width controls.
    // Unlike `ListToolbar`'s filters slot these are rendered directly by the screen,
    // so the row has to be declared here or each child becomes its own block.
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3 lg:grid-cols-4">
      <div>
        <Input
          placeholder={t("itemFilters.featurePlaceholder")}
          value={currentFilters.feature ?? ""}
          onChange={(event) =>
            onFiltersChange({
              ...currentFilters,
              feature: event.target.value || undefined,
            })
          }
          aria-label={t("itemFilters.featureAria")}
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
          <SelectTrigger className="w-full" aria-label={t("itemFilters.statusAria")}>
            {/* Base UI renders the raw selected value, not the item's label, so
                without this the trigger reads "any" or "pass" instead of the
                wording in the menu. */}
            <SelectValue>
              {(value: string) =>
                value === ANY
                  ? t("itemFilters.allStatuses")
                  : t(`itemFilters.statuses.${value as ChecklistItemStatus}`)
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{t("itemFilters.allStatuses")}</SelectItem>
            {STATUSES.map((key) => (
              <SelectItem key={key} value={key}>
                {t(`itemFilters.statuses.${key}`)}
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
          <SelectTrigger className="w-full" aria-label={t("itemFilters.kindAria")}>
            <SelectValue>
              {(value: string) =>
                value === ANY
                  ? t("itemFilters.allKinds")
                  : t(`kinds.${value as ChecklistItemKind}`)
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{t("itemFilters.allKinds")}</SelectItem>
            {KINDS.map((key) => (
              <SelectItem key={key} value={key}>
                {t(`kinds.${key}`)}
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
          <SelectTrigger className="w-full" aria-label={t("itemFilters.sourceAria")}>
            {/* Base UI renders the raw selected value, not the item's label, so
                without this the trigger reads "any" or "pass" instead of the
                wording in the menu. */}
            <SelectValue>
              {(value: string) =>
                value === ANY
                  ? t("itemFilters.allSources")
                  : t(`itemFilters.sources.${value as ChecklistItemSource}`)
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{t("itemFilters.allSources")}</SelectItem>
            {SOURCES.map((key) => (
              <SelectItem key={key} value={key}>
                {t(`itemFilters.sources.${key}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

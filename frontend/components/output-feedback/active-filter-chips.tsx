"use client";

import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";

/** The filters a shared link can carry that the filter row has no control for. */
export type UrlOnlyFilter = "projectId" | "promptVersion";

/**
 * A removable chip for each active URL-only filter, so a link carrying `?projectId=…`
 * says it is filtering and can be cleared (`docs/ui-audit-findings.md` §U3.6).
 *
 * `projectName` comes from a cached read (a row of the list already loaded) and is
 * absent until one arrives; the chip then shows a short id rather than nothing.
 */
export function ActiveFilterChips({
  filters,
  projectName,
  onRemove,
}: {
  filters: { projectId?: string; promptVersion?: string };
  projectName?: string;
  onRemove: (key: UrlOnlyFilter) => void;
}) {
  const t = useTranslations("outputFeedback.filters");

  const chips: { key: UrlOnlyFilter; label: string }[] = [];
  if (filters.projectId) {
    chips.push({
      key: "projectId",
      label: t("projectChip", { value: projectName ?? filters.projectId.slice(0, 8) }),
    });
  }
  if (filters.promptVersion) {
    chips.push({
      key: "promptVersion",
      label: t("promptVersionChip", { value: filters.promptVersion }),
    });
  }

  if (chips.length === 0) return null;

  return (
    <ul className="flex flex-wrap items-center gap-2">
      {chips.map(({ key, label }) => (
        <li key={key}>
          <Badge variant="secondary" className="h-6 pe-1">
            {label}
            <button
              type="button"
              className="hover:bg-muted rounded-full p-0.5"
              aria-label={t("removeFilter", { label })}
              onClick={() => onRemove(key)}
            >
              <X />
            </button>
          </Badge>
        </li>
      ))}
    </ul>
  );
}

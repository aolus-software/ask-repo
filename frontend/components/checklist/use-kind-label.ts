"use client";

import { useTranslations } from "next-intl";

import type { ChecklistItemKind } from "@/lib/api/types";

/** A test case kind's display name, from `checklist.kinds`. */
export function useKindLabel(): (kind: ChecklistItemKind) => string {
  const t = useTranslations("checklist.kinds");
  return (kind) => t(kind);
}

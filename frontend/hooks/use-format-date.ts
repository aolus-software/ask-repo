"use client";

import { useLocale } from "next-intl";

import { formatRelative } from "@/lib/dates";

/** `formatRelative` bound to the active locale. */
export function useFormatRelative(): (iso: string) => string {
  const locale = useLocale();
  return (iso) => formatRelative(iso, locale);
}

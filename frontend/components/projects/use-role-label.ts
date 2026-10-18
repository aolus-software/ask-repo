"use client";

import { useTranslations } from "next-intl";

const SEEDED_ROLES = ["viewer", "editor", "owner"] as const;

/**
 * A role's display name. The three seeded roles are translated; a custom role's name
 * is an admin-entered identifier and is shown as written.
 */
export function useRoleLabel(): (name: string) => string {
  const t = useTranslations("projects.roles");
  return (name) =>
    (SEEDED_ROLES as readonly string[]).includes(name)
      ? t(name as (typeof SEEDED_ROLES)[number])
      : name;
}

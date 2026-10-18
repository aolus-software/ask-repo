"use client";

import { useTranslations } from "next-intl";

import { useSession } from "@/hooks/use-session";
import { useRoles } from "@/hooks/use-roles";

/**
 * The three roles `role_seed.py` guarantees always exist, for callers that cannot
 * fetch the full catalogue (see below).
 */
const SYSTEM_ROLES = ["viewer", "editor", "owner"] as const;
type SystemRole = (typeof SYSTEM_ROLES)[number];

function isSystemRole(name: string): name is SystemRole {
  return (SYSTEM_ROLES as readonly string[]).includes(name);
}

/**
 * Role names a caller may grant or change a member to, on the current project.
 *
 * `GET /roles` — the only endpoint listing custom roles — is admin-only
 * (`test_a_non_admin_cannot_list_roles`), but `membership.grant` is a project-level
 * permission a non-admin owner can hold. Fetching it unconditionally would 403 for
 * that caller, so only an instance admin gets the live catalogue (custom roles
 * included); everyone else sees the three system roles, which always exist.
 */
export function useRoleOptions(): { name: string; label: string }[] {
  const user = useSession();
  const query = useRoles({ enabled: user.isAdmin });
  const t = useTranslations("roles.systemRoles");

  // A system role's label is translated; a custom role's name is the admin's own and
  // is shown as written (capitalised, as it always was).
  const label = (name: string): string =>
    isSystemRole(name) ? t(name) : name.charAt(0).toUpperCase() + name.slice(1);

  if (user.isAdmin && query.data) {
    return query.data.map((role) => ({ name: role.name, label: label(role.name) }));
  }
  return SYSTEM_ROLES.map((name) => ({ name, label: label(name) }));
}

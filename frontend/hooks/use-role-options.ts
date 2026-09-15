"use client";

import { useSession } from "@/hooks/use-session";
import { useRoles } from "@/hooks/use-roles";

/**
 * The three roles `role_seed.py` guarantees always exist, for callers that cannot
 * fetch the full catalogue (see below).
 */
const SYSTEM_ROLE_LABELS: Record<string, string> = {
  viewer: "Viewer",
  editor: "Editor",
  owner: "Owner",
};

function label(name: string): string {
  return SYSTEM_ROLE_LABELS[name] ?? name.charAt(0).toUpperCase() + name.slice(1);
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

  if (user.isAdmin && query.data) {
    return query.data.map((role) => ({ name: role.name, label: label(role.name) }));
  }
  return Object.keys(SYSTEM_ROLE_LABELS).map((name) => ({ name, label: label(name) }));
}

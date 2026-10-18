"use client";

import { useSession } from "@/hooks/use-session";
import { useRoles } from "@/hooks/use-roles";

/**
 * The three roles `role_seed.py` guarantees always exist, for callers that cannot
 * fetch the full catalogue (see below).
 */
const SYSTEM_ROLES = ["viewer", "editor", "owner"] as const;

/**
 * Role names a caller may grant or change a member to, on the current project. Names
 * only: a caller shows each through `useRoleLabel`, which translates the seeded roles
 * and leaves a custom role's name as written.
 *
 * `GET /roles` — the only endpoint listing custom roles — is admin-only
 * (`test_a_non_admin_cannot_list_roles`), but `membership.grant` is a project-level
 * permission a non-admin owner can hold. Fetching it unconditionally would 403 for
 * that caller, so only an instance admin gets the live catalogue (custom roles
 * included); everyone else sees the three system roles, which always exist.
 */
export function useRoleOptions(): { name: string }[] {
  const user = useSession();
  const query = useRoles({ enabled: user.isAdmin });

  if (user.isAdmin && query.data) {
    return query.data.map((role) => ({ name: role.name }));
  }
  return SYSTEM_ROLES.map((name) => ({ name }));
}

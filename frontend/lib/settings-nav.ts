import { Bell, ScrollText, ShieldCheck, Users } from "lucide-react";

import type { NavChild } from "@/lib/nav-child";

/**
 * Settings' children.
 *
 * Notifications is the first one that is **not** admin-only. That matters beyond this
 * line: `/settings` is not a screen, it redirects to its first reachable child, so a
 * non-admin previously reached the group at all and now lands here.
 */
export const settingsNav: NavChild[] = [
  { title: "Users", href: "/settings/users", icon: Users, adminOnly: true },
  { title: "Roles", href: "/settings/roles", icon: ShieldCheck, adminOnly: true },
  { title: "Audit trail", href: "/settings/audit", icon: ScrollText, adminOnly: true },
  { title: "Notifications", href: "/settings/notifications", icon: Bell },
];

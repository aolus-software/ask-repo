import { ScrollText, ShieldCheck, Users } from "lucide-react";

import type { NavChild } from "@/lib/nav-child";

/**
 * Settings' children — all administrator-only.
 *
 * Notification preferences used to live here as the one non-admin child; they moved to
 * `/profile`, because they belong to a person rather than to the instance. With no
 * reachable child, `visibleNavTree` hides the whole group from a non-admin.
 */
export const settingsNav: NavChild[] = [
  { title: "Users", href: "/settings/users", icon: Users, adminOnly: true },
  { title: "Roles", href: "/settings/roles", icon: ShieldCheck, adminOnly: true },
  { title: "Audit trail", href: "/settings/audit", icon: ScrollText, adminOnly: true },
];

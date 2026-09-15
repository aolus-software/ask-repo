import { ShieldCheck, Users } from "lucide-react";

import type { NavChild } from "@/lib/nav-child";

/** Settings' children. Roles is admin-only, like Users. */
export const settingsNav: NavChild[] = [
  { title: "Users", href: "/settings/users", icon: Users, adminOnly: true },
  { title: "Roles", href: "/settings/roles", icon: ShieldCheck, adminOnly: true },
];

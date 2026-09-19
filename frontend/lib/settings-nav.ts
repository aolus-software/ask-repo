import { ScrollText, ShieldCheck, Users } from "lucide-react";

import type { NavChild } from "@/lib/nav-child";

/** Settings' children. All three are admin-only. */
export const settingsNav: NavChild[] = [
  { title: "Users", href: "/settings/users", icon: Users, adminOnly: true },
  { title: "Roles", href: "/settings/roles", icon: ShieldCheck, adminOnly: true },
  { title: "Audit trail", href: "/settings/audit", icon: ScrollText, adminOnly: true },
];

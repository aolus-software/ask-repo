import { Users } from "lucide-react";

import type { NavChild } from "@/lib/nav-child";

/** Settings' children. One so far; M4 adds nothing here. */
export const settingsNav: NavChild[] = [
  { title: "Users", href: "/settings/users", icon: Users, adminOnly: true },
];

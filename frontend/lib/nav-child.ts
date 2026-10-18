import type { LucideIcon } from "lucide-react";

import type en from "@/messages/en/index";

/** A key under `nav.items` in the catalogue. */
export type NavKey = keyof typeof en.nav.items;

/**
 * The shared child shape, in a leaf module both sides depend on.
 *
 * `nav.ts` imports each group's list as a VALUE, so a group module importing this
 * type back from `nav.ts` would close an import cycle. This keeps the graph one-way
 * (`.claude/rules/navigation.md` §1).
 */
export interface NavChild {
  /** Message key, translated where it renders. The href stays here only. */
  titleKey: NavKey;
  href: string;
  icon?: LucideIcon;
  /** Phase 1 has exactly one axis of authority, so this is a boolean, not a permission string. */
  adminOnly?: boolean;
}

import type { LucideIcon } from "lucide-react";

/**
 * The shared child shape, in a leaf module both sides depend on.
 *
 * `nav.ts` imports each group's list as a VALUE, so a group module importing this
 * type back from `nav.ts` would close an import cycle. This keeps the graph one-way
 * (`.claude/rules/navigation.md` §1).
 */
export interface NavChild {
  title: string;
  href: string;
  icon?: LucideIcon;
  /** Phase 1 has exactly one axis of authority, so this is a boolean, not a permission string. */
  adminOnly?: boolean;
}

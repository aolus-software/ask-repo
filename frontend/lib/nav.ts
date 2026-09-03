import {
  ClipboardCheck,
  FolderGit2,
  LayoutDashboard,
  type LucideIcon,
  MessagesSquare,
  Settings,
} from "lucide-react";

import type { NavChild } from "@/lib/nav-child";
import { settingsNav } from "@/lib/settings-nav";

export interface NavItem {
  title: string;
  href: string;
  icon: LucideIcon;
  adminOnly?: boolean;
  /** Present only on a group. A leaf has no `children` key at all. */
  children?: NavChild[];
}

export type VisibleNavItem = Omit<NavItem, "children"> & { children?: NavChild[] };

interface NavUser {
  isAdmin: boolean;
}

/**
 * The only place destinations are declared. The sidebar and the breadcrumbs both read
 * this, so they cannot drift. Never hardcode a nav label or href in a component.
 */
export const navItems: NavItem[] = [
  { title: "Dashboard", href: "/", icon: LayoutDashboard },
  { title: "Projects", href: "/projects", icon: FolderGit2 },
  { title: "Ask", href: "/ask", icon: MessagesSquare },
  { title: "Checklist", href: "/checklist", icon: ClipboardCheck },
  { title: "Settings", href: "/settings", icon: Settings, children: settingsNav },
];

function isReachable(item: { adminOnly?: boolean }, user: NavUser): boolean {
  return !item.adminOnly || user.isAdmin;
}

/**
 * The items this operator can reach, children already resolved and filtered.
 *
 * Pure, so the filtering is tested without React, and the sidebar is a thin renderer
 * that computes nothing (`navigation.md` §2).
 */
export function visibleNavTree(user: NavUser): VisibleNavItem[] {
  const tree: VisibleNavItem[] = [];

  for (const item of navItems) {
    if (!isReachable(item, user)) continue;

    if (!item.children) {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars -- strips `children` so a leaf has no such key
      const { children, ...leaf } = item;
      tree.push(leaf);
      continue;
    }

    const children = item.children.filter((child) => isReachable(child, user));
    // A group that opens onto nothing is broken UI, so it is hidden entirely.
    if (children.length === 0) continue;
    tree.push({ ...item, children });
  }

  return tree;
}

export interface Crumb {
  href: string;
  label: string;
}

/**
 * The breadcrumb trail for a path, resolved by longest matching nav item. A trailing
 * segment that matches no nav item (a resource id) becomes a final crumb whose label
 * the page overrides once it knows the resource's name.
 */
export function resolveBreadcrumbs(pathname: string, user: NavUser): Crumb[] {
  if (pathname === "/") return [];

  const tree = visibleNavTree(user);
  const trail: Crumb[] = [];

  for (const item of tree) {
    if (item.href === "/" || !pathname.startsWith(item.href)) continue;
    trail.push({ href: item.href, label: item.title });

    for (const child of item.children ?? []) {
      if (pathname.startsWith(child.href))
        trail.push({ href: child.href, label: child.title });
    }
  }

  const deepest = trail.at(-1);
  if (deepest && deepest.href !== pathname) {
    trail.push({ href: pathname, label: pathname.slice(deepest.href.length + 1) });
  }

  return trail;
}

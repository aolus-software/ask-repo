"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Sidebar,
  SidebarContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from "@/components/ui/sidebar";
import { useSession } from "@/hooks/use-session";
import { type VisibleNavItem, visibleNavTree } from "@/lib/nav";

/**
 * One collapsible nav group, held **controlled**.
 *
 * The obvious version passes `defaultOpen={pathname.startsWith(item.href)}` — but
 * `defaultOpen` is only read when the component mounts, and this component survives
 * navigation. Moving from `/projects` into `/settings/users` therefore changes
 * `defaultOpen` on an already-initialised uncontrolled Collapsible, which Base UI
 * warns about and, worse, silently ignores: the group would not expand.
 *
 * So the open state is owned here and synced on the *transition* into or out of the
 * group, during render rather than from an effect (`forms.md` §6). Syncing on the
 * transition rather than on every render is what lets an operator collapse a group
 * they are currently inside and have it stay collapsed.
 */
function NavGroup({ item, pathname }: { item: VisibleNavItem; pathname: string }) {
  const isInside = pathname.startsWith(item.href);
  const [open, setOpen] = useState(isInside);
  const [wasInside, setWasInside] = useState(isInside);

  if (isInside !== wasInside) {
    setWasInside(isInside);
    setOpen(isInside);
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen} render={<SidebarMenuItem />}>
      {/* The parent row is a trigger, not a link: a group's index route only
          redirects to its first child, which is where the expanded list
          already points. */}
      <CollapsibleTrigger render={<SidebarMenuButton />}>
        {item.icon ? <item.icon className="size-4" /> : null}
        <span>{item.title}</span>
        <ChevronRight className="ml-auto size-4 transition-transform group-data-[panel-open]:rotate-90" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <SidebarMenuSub>
          {(item.children ?? []).map((child) => (
            <SidebarMenuSubItem key={child.href}>
              <SidebarMenuSubButton
                isActive={pathname.startsWith(child.href)}
                render={<Link href={child.href} />}
              >
                {child.title}
              </SidebarMenuSubButton>
            </SidebarMenuSubItem>
          ))}
        </SidebarMenuSub>
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * A thin renderer over `visibleNavTree`. It computes nothing — the filtering is pure
 * and tested without React (`.claude/rules/navigation.md` §2).
 */
export function AppSidebar() {
  const user = useSession();
  const pathname = usePathname();
  const tree = visibleNavTree(user);

  return (
    <Sidebar className="top-16 h-[calc(100vh-4rem)]">
      <SidebarContent className="p-2">
        <SidebarMenu>
          {tree.map((item) =>
            item.children ? (
              <NavGroup key={item.href} item={item} pathname={pathname} />
            ) : (
              <SidebarMenuItem key={item.href}>
                <SidebarMenuButton
                  isActive={
                    item.href === "/"
                      ? pathname === "/"
                      : pathname.startsWith(item.href)
                  }
                  render={<Link href={item.href} />}
                >
                  <item.icon className="size-4" />
                  <span>{item.title}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ),
          )}
        </SidebarMenu>
      </SidebarContent>
    </Sidebar>
  );
}

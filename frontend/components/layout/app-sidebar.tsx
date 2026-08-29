"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
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
import { visibleNavTree } from "@/lib/nav";

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
              <Collapsible
                key={item.href}
                // Opens already expanded when the route is inside it, so a deep link
                // lands with its section visible.
                defaultOpen={pathname.startsWith(item.href)}
                render={<SidebarMenuItem />}
              >
                {/* The parent row is a trigger, not a link: a group's index route only
                    redirects to its first child, which is where the expanded list
                    already points. */}
                <CollapsibleTrigger render={<SidebarMenuButton />}>
                  <item.icon className="size-4" />
                  <span>{item.title}</span>
                  <ChevronRight className="ml-auto size-4 transition-transform group-data-[panel-open]:rotate-90" />
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <SidebarMenuSub>
                    {item.children.map((child) => (
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
            ) : (
              <SidebarMenuItem key={item.href}>
                <SidebarMenuButton
                  isActive={item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)}
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

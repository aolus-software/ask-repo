"use client";

import { LogOut, MonitorSmartphone, UserRound } from "lucide-react";
import Link from "next/link";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSession } from "@/hooks/use-session";

function initials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * Who is signed in, the way to their profile, and the two sign-out actions.
 * Everything else about the account lives on `/profile`.
 */
export function AccountMenu() {
  const user = useSession();

  async function logout(all: boolean) {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ all }),
    });
    // A hard reload, not router.push, and the lint rule is suppressed deliberately:
    // router.push keeps the SPA alive, and with it the React Query cache holding the
    // previous operator's projects and conversations. On a shared machine the next
    // person would see that stale data flash before it refetched. A full load drops it.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- clears the in-memory cache with the session
    window.location.href = "/login";
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" size="icon" aria-label="Account" />}
      >
        <Avatar className="size-8">
          <AvatarFallback>{initials(user.name)}</AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {/* Base UI requires a group label inside a Group, or it throws at render. */}
        <DropdownMenuGroup>
          <DropdownMenuLabel>
            <span className="text-foreground block truncate text-sm font-medium">
              {user.name}
            </span>
            <span className="text-muted-foreground block truncate text-xs font-normal">
              {user.email}
            </span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<Link href="/profile" />}>
          <UserRound className="size-4" />
          Profile
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => void logout(false)}>
          <LogOut className="size-4" />
          Log out
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => void logout(true)}>
          <MonitorSmartphone className="size-4" />
          Log out everywhere
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

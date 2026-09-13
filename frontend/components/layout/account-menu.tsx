"use client";

import { LogOut, MonitorSmartphone } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
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
 * Deliberately just the sign-out actions for now, no profile display and no
 * change-password entry — both are coming back once there is a proper account
 * settings page for them to live on. Voluntary self-service password change is
 * therefore unreachable from the UI until then; the forced first-login flow at
 * `/change-password` is a separate route and is unaffected.
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
      <DropdownMenuContent align="end" className="w-48">
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

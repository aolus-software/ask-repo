"use client";

import { KeyRound, LogOut, MonitorSmartphone } from "lucide-react";
import { useState } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ChangePasswordDialog } from "@/components/users/change-password-dialog";
import { useSession } from "@/hooks/use-session";

function initials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function AccountMenu() {
  const user = useSession();
  const [changingPassword, setChangingPassword] = useState(false);

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
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={<Button variant="ghost" size="icon" aria-label="Account" />}
        >
          <Avatar className="size-8">
            <AvatarFallback>{initials(user.name)}</AvatarFallback>
          </Avatar>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuLabel>
            <span className="block font-medium">{user.name}</span>
            <span className="text-muted-foreground block text-xs">{user.email}</span>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => setChangingPassword(true)}>
            <KeyRound className="size-4" />
            Change password
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

      <ChangePasswordDialog
        open={changingPassword}
        onOpenChange={setChangingPassword}
      />
    </>
  );
}

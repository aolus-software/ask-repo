"use client";

import Image from "next/image";
import Link from "next/link";

import { AccountMenu } from "@/components/layout/account-menu";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { SidebarTrigger } from "@/components/ui/sidebar";

/** Fixed, h-16. That 4rem is load-bearing: the sidebar's top and height derive from it. */
export function AppNavbar() {
  return (
    <header className="bg-card border-border fixed inset-x-0 top-0 z-50 flex h-16 items-center gap-4 border-b px-4 md:px-8">
      <SidebarTrigger className="md:hidden" aria-label="Toggle navigation" />
      <Link
        href="/"
        className="text-foreground flex items-center gap-2 text-xl font-semibold tracking-tight"
      >
        {/* Decorative: the wordmark beside it already names the app, so a second
            reading of "AskRepo" would only repeat itself to a screen reader.
            The mark is a transparent gradient that reads on either theme, so it
            needs no `dark:` treatment. */}
        <Image
          src="/logo.png"
          alt=""
          width={32}
          height={32}
          className="size-8"
          priority
        />
        AskRepo
      </Link>
      <div className="ml-auto flex items-center gap-2">
        <ThemeToggle />
        <AccountMenu />
      </div>
    </header>
  );
}

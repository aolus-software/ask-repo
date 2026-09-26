"use client";

import { useState, useSyncExternalStore } from "react";

import { AccountSection } from "@/components/profile/account-section";
import { ActivitySection } from "@/components/profile/activity-section";
import { PasswordSection } from "@/components/profile/password-section";
import { SessionsSection } from "@/components/profile/sessions-section";
import { PageHeader } from "@/components/layout/page-header";
import { PreferencesScreen } from "@/components/notifications/preferences-screen";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const SECTIONS = [
  { id: "account", title: "Account" },
  { id: "sessions", title: "Sessions" },
  { id: "activity", title: "Activity" },
  { id: "notifications", title: "Notifications" },
  { id: "password", title: "Password" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

function isSectionId(value: string): value is SectionId {
  return SECTIONS.some((section) => section.id === value);
}

function subscribeToHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/**
 * The section the URL names, or `null`. Read through `useSyncExternalStore` so the
 * server render (no hash) and the first client render agree, and so a
 * `/settings/notifications` redirect to `#notifications` opens that tab.
 */
function useHashSection(): SectionId | null {
  const hash = useSyncExternalStore(
    subscribeToHash,
    () => window.location.hash.slice(1),
    () => "",
  );
  return isSectionId(hash) ? hash : null;
}

/**
 * One section at a time, chosen from a vertical tab list styled like the app sidebar:
 * a card, with the active row in the sidebar's accent. The URL hash follows the tab,
 * so a reload or a shared link lands on the same section.
 */
export function ProfileScreen({ resetEnabled }: { resetEnabled: boolean }) {
  const fromHash = useHashSection();
  const [selected, setSelected] = useState<SectionId | null>(null);
  const active = selected ?? fromHash ?? "account";

  const body: Record<SectionId, React.ReactNode> = {
    account: <AccountSection />,
    sessions: <SessionsSection />,
    activity: <ActivitySection />,
    notifications: <PreferencesScreen />,
    password: <PasswordSection resetEnabled={resetEnabled} />,
  };

  function select(value: unknown) {
    if (typeof value !== "string" || !isSectionId(value)) return;
    setSelected(value);
    // `replaceState`, not `location.hash`: switching tabs should not stack history
    // entries, and assigning the hash would scroll to any element with that id.
    window.history.replaceState(null, "", `#${value}`);
  }

  return (
    <div className="mx-auto w-full max-w-5xl">
      <PageHeader title="Profile" description="Your account, sessions and settings." />
      <Tabs
        orientation="vertical"
        value={active}
        onValueChange={select}
        className="flex-col gap-6 lg:flex-row"
      >
        <TabsList
          aria-label="Profile sections"
          className="bg-card border-border w-full shrink-0 items-stretch gap-1 self-start border p-2 lg:sticky lg:top-24 lg:w-48"
        >
          {/* The `!` overrides beat the generated trigger's own `dark:data-active:*`
              colours, so the active row matches the sidebar in both themes without a
              `dark:` colour utility here (design-system.md §3). */}
          {SECTIONS.map((section) => (
            <TabsTrigger
              key={section.id}
              value={section.id}
              className="hover:bg-sidebar-accent/60 data-active:bg-sidebar-accent! data-active:text-sidebar-accent-foreground! h-auto justify-start px-3 py-2 data-active:border-transparent! data-active:shadow-none!"
            >
              {section.title}
            </TabsTrigger>
          ))}
        </TabsList>
        {SECTIONS.map((section) => (
          <TabsContent key={section.id} value={section.id} className="min-w-0">
            {body[section.id]}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

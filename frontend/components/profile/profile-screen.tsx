"use client";

import { AccountSection } from "@/components/profile/account-section";
import { ActivitySection } from "@/components/profile/activity-section";
import { PasswordSection } from "@/components/profile/password-section";
import { SessionsSection } from "@/components/profile/sessions-section";
import { PageHeader } from "@/components/layout/page-header";
import { PreferencesScreen } from "@/components/notifications/preferences-screen";

const SECTIONS = [
  { id: "account", title: "Account" },
  { id: "sessions", title: "Sessions" },
  { id: "activity", title: "Activity" },
  { id: "notifications", title: "Notifications" },
  { id: "password", title: "Password" },
] as const;

/** One column of sections; on wide screens an index of anchors sits beside it. */
export function ProfileScreen({ resetEnabled }: { resetEnabled: boolean }) {
  const body: Record<(typeof SECTIONS)[number]["id"], React.ReactNode> = {
    account: <AccountSection />,
    sessions: <SessionsSection />,
    activity: <ActivitySection />,
    notifications: <PreferencesScreen />,
    password: <PasswordSection resetEnabled={resetEnabled} />,
  };

  return (
    <div className="mx-auto w-full max-w-5xl">
      <PageHeader title="Profile" description="Your account, sessions and settings." />
      <div className="grid gap-8 lg:grid-cols-[10rem_1fr]">
        <nav aria-label="Profile sections" className="hidden lg:block">
          <ul className="sticky top-24 space-y-2 text-sm">
            {SECTIONS.map((section) => (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  className="text-muted-foreground hover:text-foreground"
                >
                  {section.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 space-y-10">
          {SECTIONS.map((section) => (
            <section
              key={section.id}
              id={section.id}
              className="scroll-mt-24 space-y-3"
            >
              <h2 className="text-foreground text-lg font-semibold">{section.title}</h2>
              {body[section.id]}
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

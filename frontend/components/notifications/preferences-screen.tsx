"use client";

import { useState } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences,
} from "@/hooks/use-notifications";
import type { NotificationPreference } from "@/lib/api/types";
import { notificationTitleForType } from "@/lib/notifications";

/**
 * One row per event type, two switches each.
 *
 * The email column follows `emailEnabled`, which is the instance's `MAIL_ENABLED`.
 * With mail off the switches stay visible and disabled rather than hidden: the
 * preference a user sets now is the one honoured if an operator turns mail on.
 * Rendered inside the profile's Notifications section, which supplies the heading.
 */
export function PreferencesScreen() {
  const [draft, setDraft] = useState<NotificationPreference[] | null>(null);

  const query = useNotificationPreferences();
  const save = useUpdateNotificationPreferences();

  const items = draft ?? query.data?.items ?? [];
  const emailEnabled = query.data?.emailEnabled ?? false;

  const toggle = (eventType: string, field: "inApp" | "email") => {
    setDraft(
      items.map((item) =>
        item.eventType === eventType ? { ...item, [field]: !item[field] } : item,
      ),
    );
  };

  return (
    <div>
      {!emailEnabled && (
        <p className="border-border bg-muted text-muted-foreground mb-4 rounded-md border px-4 py-3 text-sm">
          Email delivery is turned off on this instance. Your choices are saved and will
          apply if an administrator turns it on.
        </p>
      )}

      <Card className="p-0">
        {query.isError ? (
          <div className="p-6">
            <ListError error={query.error} onRetry={() => query.refetch()} />
          </div>
        ) : !query.isLoading && items.length === 0 ? (
          <EmptyState
            title="Nothing to configure yet"
            description="This instance has no notification types to set preferences for."
          />
        ) : (
          <>
            <div className="text-muted-foreground border-border grid grid-cols-[1fr_auto_auto] items-center gap-6 border-b px-4 py-2 text-xs font-medium">
              <span>Event</span>
              <span>In app</span>
              <span>Email</span>
            </div>
            {items.map((item) => (
              <div
                key={item.eventType}
                className="border-border grid grid-cols-[1fr_auto_auto] items-center gap-6 border-b px-4 py-3 last:border-b-0"
              >
                <Label
                  htmlFor={`${item.eventType}-in-app`}
                  className="text-foreground text-sm"
                >
                  {notificationTitleForType(item.eventType)}
                </Label>
                <Switch
                  id={`${item.eventType}-in-app`}
                  checked={item.inApp}
                  onCheckedChange={() => toggle(item.eventType, "inApp")}
                />
                <Switch
                  id={`${item.eventType}-email`}
                  checked={item.email}
                  disabled={!emailEnabled}
                  onCheckedChange={() => toggle(item.eventType, "email")}
                />
              </div>
            ))}
          </>
        )}
      </Card>

      <div className="mt-4 flex justify-end">
        <Button
          disabled={draft === null || save.isPending}
          onClick={() => {
            save.mutate(items, { onSuccess: () => setDraft(null) });
          }}
        >
          Save preferences
        </Button>
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";

import { formatRelative } from "@/lib/dates";
import { notificationHref, notificationTitle } from "@/lib/notifications";
import type { NotificationSummary } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type Props = {
  notifications: NotificationSummary[];
  onRead: (id: string) => void;
  emptyMessage?: string;
};

/** The shared row rendering, used by both the popover and `/notifications`. */
export function NotificationList({ notifications, onRead, emptyMessage }: Props) {
  if (notifications.length === 0) {
    return (
      <p className="px-4 py-6 text-center text-sm text-muted-foreground">
        {emptyMessage ?? "Nothing to catch up on."}
      </p>
    );
  }

  return (
    <ul className="divide-y divide-border">
      {notifications.map((n) => (
        <li key={n.id}>
          <Link
            href={notificationHref(n)}
            onClick={() => !n.readAt && onRead(n.id)}
            className={cn(
              "flex flex-col gap-1 px-4 py-3 transition-colors hover:bg-accent",
              !n.readAt && "bg-accent/40",
            )}
          >
            <span className="text-sm text-foreground">{notificationTitle(n)}</span>
            <span className="text-xs text-muted-foreground">{formatRelative(n.createdAt)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

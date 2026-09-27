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
      <p className="text-muted-foreground px-4 py-6 text-center text-sm">
        {emptyMessage ?? "Nothing to catch up on."}
      </p>
    );
  }

  return (
    <ul className="divide-border divide-y">
      {notifications.map((n) => {
        const unread = !n.readAt;
        return (
          <li key={n.id}>
            <Link
              href={notificationHref(n)}
              onClick={() => unread && onRead(n.id)}
              className={cn(
                "flex flex-col gap-1 px-4 py-3 transition-colors",
                // The tint is a signal, not the signal: unread keeps it regardless
                // of hover, so hovering a read row never makes it look unread.
                unread ? "bg-accent/40 hover:bg-accent/60" : "hover:bg-accent/50",
              )}
            >
              <span className="flex items-center gap-2 text-sm">
                {unread ? (
                  <span
                    className="bg-primary size-2 shrink-0 rounded-full"
                    aria-hidden
                  />
                ) : null}
                <span className={cn("text-foreground", unread && "font-medium")}>
                  {notificationTitle(n)}
                </span>
                {unread ? <span className="sr-only">Unread</span> : null}
              </span>
              <span className="text-muted-foreground text-xs">
                {formatRelative(n.createdAt)}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

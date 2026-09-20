"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import Link from "next/link";

import { NotificationList } from "@/components/notifications/notification-list";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiFetch } from "@/lib/api/client";
import { endpoints, listQueryString } from "@/lib/api/endpoints";
import type { PaginatedResponse, NotificationSummary, UnreadCountResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/**
 * Polls an integer, deliberately.
 *
 * `docs/PRD.md` §2.1: the SSE machinery is built for the lifetime of one answer, and a
 * per-user notification stream is a different connection lifecycle with different
 * failure modes. `refetchIntervalInBackground: false` stops a tab left open overnight
 * from polling all night.
 */
const POLL_INTERVAL_MS = 60_000;
const POPOVER_LIMIT = 8;

export function NotificationBell() {
  const queryClient = useQueryClient();

  const count = useQuery({
    queryKey: keys.notifications.unreadCount(),
    queryFn: () => apiFetch<UnreadCountResponse>(endpoints.notifications.unreadCount),
    refetchInterval: POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
  });

  const listParams = { limit: POPOVER_LIMIT };
  const recent = useQuery({
    queryKey: keys.notifications.list(listParams),
    queryFn: () =>
      apiFetch<PaginatedResponse<NotificationSummary>>(
        `${endpoints.notifications.list}${listQueryString(listParams)}`,
      ),
  });

  const markRead = useMutation({
    mutationFn: (id: string) => apiFetch(endpoints.notifications.markRead(id), { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.notifications.all });
    },
  });

  const markAllRead = useMutation({
    mutationFn: () => apiFetch(endpoints.notifications.markAllRead, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.notifications.all });
    },
  });

  const unread = count.data?.count ?? 0;

  return (
    <Popover>
      <PopoverTrigger
        render={<Button variant="ghost" size="icon" className="relative" />}
        aria-label={`Notifications (${unread} unread)`}
      >
        <Bell className="size-4" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-medium text-primary-foreground">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-90 p-0">
        <div className="flex items-center justify-between border-b border-border px-4 py-2">
          <span className="text-sm font-medium text-foreground">Notifications</span>
          <Button
            variant="ghost"
            size="sm"
            disabled={unread === 0 || markAllRead.isPending}
            onClick={() => markAllRead.mutate()}
          >
            Mark all read
          </Button>
        </div>
        <ScrollArea className="max-h-96">
          <NotificationList
            notifications={recent.data?.items ?? []}
            onRead={(id) => markRead.mutate(id)}
          />
        </ScrollArea>
        <div className="border-t border-border px-4 py-2 text-center">
          <Link href="/notifications" className="text-sm text-primary hover:underline">
            See all
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  );
}

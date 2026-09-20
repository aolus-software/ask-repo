"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints, listQueryString } from "@/lib/api/endpoints";
import type {
  NotificationListParams,
  PaginatedResponse,
  NotificationSummary,
  UnreadCountResponse,
} from "@/lib/api/types";
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

export function useUnreadNotificationCount() {
  return useQuery({
    queryKey: keys.notifications.unreadCount(),
    queryFn: () => apiFetch<UnreadCountResponse>(endpoints.notifications.unreadCount),
    refetchInterval: POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
  });
}

/**
 * Parameterised so the popover's small fixed `limit` and the `/notifications` page's
 * paginated, filtered list are served by the same query shape and the same cache key.
 */
export function useNotifications(params: NotificationListParams) {
  return useQuery({
    queryKey: keys.notifications.list(params),
    queryFn: () =>
      apiFetch<PaginatedResponse<NotificationSummary>>(
        `${endpoints.notifications.list}${listQueryString(params)}`,
      ),
  });
}

function useNotificationInvalidation() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: keys.notifications.all });
}

export function useMarkNotificationRead() {
  const invalidate = useNotificationInvalidation();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(endpoints.notifications.markRead(id), { method: "POST" }),
    onSuccess: invalidate,
  });
}

export function useMarkAllNotificationsRead() {
  const invalidate = useNotificationInvalidation();
  return useMutation({
    mutationFn: () => apiFetch(endpoints.notifications.markAllRead, { method: "POST" }),
    onSuccess: invalidate,
  });
}

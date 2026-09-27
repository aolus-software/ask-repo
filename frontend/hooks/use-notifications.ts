"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiFetch } from "@/lib/api/client";
import { endpoints, notificationListQueryString } from "@/lib/api/endpoints";
import type {
  NotificationListParams,
  NotificationPreference,
  NotificationPreferencesResponse,
  PaginatedResponse,
  NotificationSummary,
  UnreadCountResponse,
} from "@/lib/api/types";
import { useLiveEvents } from "@/hooks/use-live-events";
import { keys } from "@/lib/query/keys";

/**
 * Polls an integer, deliberately.
 *
 * `docs/PRD.md` §2.1: the SSE machinery is built for the lifetime of one answer, and a
 * per-user notification stream is a different connection lifecycle with different
 * failure modes. `refetchIntervalInBackground: false` stops a tab left open overnight
 * from polling all night.
 *
 * `useNotifications` shares this interval (and the background rule) with
 * `useUnreadNotificationCount` below: the bell mounts both queries with no `enabled`
 * gate and no remount on popover open, so a mismatched interval would let the badge
 * and the list drift out of step for as long as the tab stays open.
 *
 * Both intervals are now the fallback and the safety net for a lost live event:
 * `connected` (from `LiveEventsProvider`) relaxes them to five minutes once the live
 * stream is delivering `invalidate` events for `notification` itself.
 */
const POLL_INTERVAL_MS = 60_000;
const CONNECTED_POLL_INTERVAL_MS = 5 * 60_000;

export function useUnreadNotificationCount() {
  const { connected } = useLiveEvents();
  return useQuery({
    queryKey: keys.notifications.unreadCount(),
    queryFn: () => apiFetch<UnreadCountResponse>(endpoints.notifications.unreadCount),
    refetchInterval: connected ? CONNECTED_POLL_INTERVAL_MS : POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
  });
}

/**
 * Parameterised so the popover's small fixed `limit` and the `/notifications` page's
 * paginated, filtered list are served by the same query shape and the same cache key.
 */
export function useNotifications(params: NotificationListParams) {
  const { connected } = useLiveEvents();
  return useQuery({
    queryKey: keys.notifications.list(params),
    queryFn: () =>
      apiFetch<PaginatedResponse<NotificationSummary>>(
        `${endpoints.notifications.list}${notificationListQueryString(params)}`,
      ),
    refetchInterval: connected ? CONNECTED_POLL_INTERVAL_MS : POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
  });
}

function useNotificationInvalidation() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: keys.notifications.all });
}

// A read failing is otherwise invisible: the row's tint does not lift and the count
// does not drop, with nothing telling the user why. Hook-level so every call site
// (the bell's popover and the /notifications header) gets it for free.
function reportMarkReadFailure(): void {
  toast.error("Couldn't mark notifications read");
}

export function useMarkNotificationRead() {
  const invalidate = useNotificationInvalidation();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(endpoints.notifications.markRead(id), { method: "POST" }),
    onSuccess: invalidate,
    onError: reportMarkReadFailure,
  });
}

export function useMarkAllNotificationsRead() {
  const invalidate = useNotificationInvalidation();
  return useMutation({
    mutationFn: () => apiFetch(endpoints.notifications.markAllRead, { method: "POST" }),
    onSuccess: invalidate,
    onError: reportMarkReadFailure,
  });
}

/** One row per event type in the catalogue, plus whether email delivery is live. */
export function useNotificationPreferences() {
  return useQuery({
    queryKey: keys.notifications.preferences(),
    queryFn: () =>
      apiFetch<NotificationPreferencesResponse>(endpoints.notifications.preferences),
  });
}

/**
 * Replaces the whole preference list in one call -- there is no per-row endpoint, so
 * the caller always sends every item back, changed or not.
 */
export function useUpdateNotificationPreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (items: NotificationPreference[]) =>
      apiFetch(endpoints.notifications.preferences, {
        method: "PUT",
        body: JSON.stringify({ items }),
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.notifications.preferences() }),
  });
}

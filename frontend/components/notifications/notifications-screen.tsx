"use client";

import { Bell } from "lucide-react";

import { NotificationFilters } from "@/components/notifications/notification-filters";
import { NotificationList } from "@/components/notifications/notification-list";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { ListToolbar } from "@/components/layout/list-toolbar";
import { PageHeader } from "@/components/layout/page-header";
import { PaginationFooter } from "@/components/layout/pagination-footer";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
  useUnreadNotificationCount,
} from "@/hooks/use-notifications";
import { useListParams } from "@/hooks/use-list-params";
import type { NotificationListParams } from "@/lib/api/types";

const EXTRA_PARAMS = ["unreadOnly", "projectId", "eventType"] as const;

/**
 * `setParam` reads the current URL on every call, so firing it once per changed key
 * would have each call clobber the one before it within the same event handler.
 * `NotificationFilters` only ever changes one field per interaction, so diffing
 * against the params already on the URL and writing the single key that moved keeps
 * this to one `setParam` call per change — the same trick `AuditFilters` uses.
 */
function changedKey(
  next: Partial<NotificationListParams>,
  current: Partial<NotificationListParams>,
): (typeof EXTRA_PARAMS)[number] | undefined {
  return EXTRA_PARAMS.find((key) => next[key] !== current[key]);
}

export function NotificationsScreen() {
  const { params, setPage, setParam } = useListParams(
    { limit: 25 },
    { extraParams: EXTRA_PARAMS },
  );
  const listParams = params as NotificationListParams;
  const query = useNotifications(listParams);
  const notifications = query.data?.items ?? [];

  const unreadCount = useUnreadNotificationCount();
  const markRead = useMarkNotificationRead();
  const markAllRead = useMarkAllNotificationsRead();

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="Notifications"
        description="Everything AskRepo has told you about, newest first."
        action={
          <Button
            variant="outline"
            disabled={(unreadCount.data?.count ?? 0) === 0 || markAllRead.isPending}
            onClick={() => markAllRead.mutate()}
          >
            Mark all read
          </Button>
        }
      />

      <ListToolbar
        columns={3}
        filters={
          <NotificationFilters
            currentFilters={listParams}
            onFiltersChange={(filters) => {
              const key = changedKey(filters, listParams);
              if (key) {
                const value = filters[key];
                setParam(
                  key,
                  key === "unreadOnly"
                    ? value
                      ? "true"
                      : undefined
                    : (value as string | undefined),
                );
              }
            }}
          />
        }
      />

      <Card className="p-0">
        {query.isError ? (
          <div className="p-6">
            <ListError error={query.error} onRetry={() => query.refetch()} />
          </div>
        ) : !query.isLoading && notifications.length === 0 ? (
          <EmptyState
            icon={Bell}
            title={
              listParams.projectId || listParams.eventType || listParams.unreadOnly
                ? "No notifications match"
                : "Nothing yet"
            }
            description={
              listParams.projectId || listParams.eventType || listParams.unreadOnly
                ? "Try clearing your filters."
                : "Project and checklist events will appear here as they happen."
            }
          />
        ) : (
          <>
            <NotificationList
              notifications={notifications}
              onRead={(id) => markRead.mutate(id)}
            />
            <PaginationFooter
              page={query.data?.page ?? 1}
              totalPages={query.data?.totalPages ?? 1}
              totalCount={query.data?.totalCount ?? 0}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>
    </div>
  );
}

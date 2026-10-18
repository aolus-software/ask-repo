/**
 * The notification vocabulary, mirrored from `NotificationType` in
 * `backend/app/core/notifications.py`, plus the two pure functions that turn a row
 * into something renderable.
 *
 * `eventType` is a plain string on the wire — the catalogue is enforced on the write
 * side by `tests/test_notification_coverage.py` — so this list is the filter's option
 * set, not a validated enum, and every function here must survive a type it has never
 * seen. A backend that ships a twelfth event must not blank this screen.
 *
 * The wording lives here rather than in the row. A notification stores structured
 * fields precisely so a renamed module reads correctly in a month-old notification.
 */

import type { useTranslations } from "next-intl";

import type { NotificationSummary } from "@/lib/api/types";

export const NOTIFICATION_TYPES = [
  "project.ready",
  "project.failed",
  "project.reindex.finished",
  "project.reindex.failed",
  "checklist_change_set.pending",
  "checklist_change_set.applied",
  "checklist_change_set.discarded",
  "mock_data_change_set.pending",
  "mock_data_change_set.applied",
  "mock_data_change_set.discarded",
  "membership.granted",
  "eval_set.ready",
  "eval_set.failed",
  "eval_run.finished",
  "eval_run.failed",
] as const;

/**
 * Where clicking this notification goes.
 *
 * Both change-set families target the checklist module, not the change set: the Mock
 * Data tab is part of `/checklist/[moduleId]` rather than a route of its own, and a
 * change set's own id names nothing anyone can navigate to. The backend already stores
 * the module id as `targetId` for exactly this reason. Both eval families target the
 * set for the same reason: a run's results live on its set's screen.
 */
export function notificationHref(n: NotificationSummary): string {
  if (n.targetType === "checklist_module" && n.targetId) {
    return `/checklist/${n.targetId}`;
  }
  if (n.targetType === "eval_set" && n.targetId) {
    return `/projects/${n.projectId}/eval/${n.targetId}`;
  }
  return `/projects/${n.projectId}`;
}

/** A translator scoped to the `notifications` namespace. */
type NotificationsT = ReturnType<typeof useTranslations<"notifications">>;

/** The catalogue key for an event type: the name with `.` replaced by `_`. */
function typeKey(eventType: string): string {
  return eventType.replaceAll(".", "_");
}

/**
 * A human sentence for one notification, falling back to the raw type.
 *
 * The template is translated; `details` supplies names the admin typed (a project, a
 * module, a role), which are interpolated as written and never translated.
 */
export function notificationTitle(n: NotificationSummary, t: NotificationsT): string {
  const key = `titles.${typeKey(n.eventType)}`;
  if (!t.has(key as never)) return n.eventType;
  const untitled = t("untitled");
  const name = (field: string): string => {
    const value = n.details[field];
    return typeof value === "string" && value ? value : untitled;
  };
  return t(
    key as never,
    {
      projectName: name("projectName"),
      moduleName: name("moduleName"),
      roleName: name("roleName"),
      setName: name("setName"),
    } as never,
  );
}

/**
 * A label for the *category* an event type belongs to, not for one row.
 *
 * Used on the preferences screen, where there is no `NotificationSummary` to pull a
 * project or module name from -- only the bare `eventType` the backend's catalogue
 * enumerates. Falls back to the raw type for the same reason `notificationTitle`
 * does: a backend that ships a new event type must not blank this screen.
 */
export function notificationTitleForType(eventType: string, t: NotificationsT): string {
  const key = `categories.${typeKey(eventType)}`;
  return t.has(key as never) ? t(key as never) : eventType;
}

/** A short label for an event type, for the filter's options. */
export function notificationTypeLabel(eventType: string, t: NotificationsT): string {
  const key = `types.${typeKey(eventType)}`;
  return t.has(key as never) ? t(key as never) : eventType;
}

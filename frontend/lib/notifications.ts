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
] as const;

/**
 * Where clicking this notification goes.
 *
 * Both change-set families target the checklist module, not the change set: the Mock
 * Data tab is part of `/checklist/[moduleId]` rather than a route of its own, and a
 * change set's own id names nothing anyone can navigate to. The backend already stores
 * the module id as `targetId` for exactly this reason.
 */
export function notificationHref(n: NotificationSummary): string {
  if (n.targetType === "checklist_module" && n.targetId) {
    return `/checklist/${n.targetId}`;
  }
  return `/projects/${n.projectId}`;
}

const TITLES: Record<string, (d: Record<string, unknown>) => string> = {
  "project.ready": (d) => `${name(d, "projectName")} finished indexing`,
  "project.failed": (d) => `${name(d, "projectName")} failed to index`,
  "project.reindex.finished": (d) => `${name(d, "projectName")} finished reindexing`,
  "project.reindex.failed": (d) => `${name(d, "projectName")} failed to reindex`,
  "checklist_change_set.pending": (d) =>
    `${name(d, "moduleName")} has a checklist change set waiting for review`,
  "checklist_change_set.applied": (d) =>
    `A checklist change set was applied to ${name(d, "moduleName")}`,
  "checklist_change_set.discarded": (d) =>
    `A checklist change set for ${name(d, "moduleName")} was discarded`,
  "mock_data_change_set.pending": (d) =>
    `${name(d, "moduleName")} has a mock data change set waiting for review`,
  "mock_data_change_set.applied": (d) =>
    `A mock data change set was applied to ${name(d, "moduleName")}`,
  "mock_data_change_set.discarded": (d) =>
    `A mock data change set for ${name(d, "moduleName")} was discarded`,
  "membership.granted": (d) =>
    `You were added to ${name(d, "projectName")} as ${name(d, "roleName")}`,
};

/** A human sentence for one notification, falling back to the raw type. */
export function notificationTitle(n: NotificationSummary): string {
  const render = TITLES[n.eventType];
  return render ? render(n.details) : n.eventType;
}

/**
 * A label for the *category* an event type belongs to, not for one row.
 *
 * Used on the preferences screen, where there is no `NotificationSummary` to pull a
 * project or module name from -- only the bare `eventType` the backend's catalogue
 * enumerates. Falls back to the raw type for the same reason `notificationTitle`
 * does: a backend that ships a new event type must not blank this screen.
 */
const CATEGORY_TITLES: Record<string, string> = {
  "project.ready": "A project finished indexing",
  "project.failed": "A project failed to index",
  "project.reindex.finished": "A project finished reindexing",
  "project.reindex.failed": "A project failed to reindex",
  "checklist_change_set.pending": "A checklist change set is waiting for review",
  "checklist_change_set.applied": "A checklist change set was applied",
  "checklist_change_set.discarded": "A checklist change set was discarded",
  "mock_data_change_set.pending": "A mock data change set is waiting for review",
  "mock_data_change_set.applied": "A mock data change set was applied",
  "mock_data_change_set.discarded": "A mock data change set was discarded",
  "membership.granted": "You were added to a project",
};

/** A human label for an event *type*, for the preferences screen's row headings. */
export function notificationTitleForType(eventType: string): string {
  return CATEGORY_TITLES[eventType] ?? eventType;
}

function name(details: Record<string, unknown>, key: string): string {
  const value = details[key];
  return typeof value === "string" && value ? value : "Untitled";
}

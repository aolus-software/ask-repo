import type { QueryKey } from "@tanstack/react-query";

import { keys } from "@/lib/query/keys";

export type LiveKind = "project" | "checklist_module" | "mock_data" | "notification";

/** The `invalidate` event's payload. Ids only — the refetch is what shows the change. */
export interface InvalidatePayload {
  kind: LiveKind;
  id: string;
  projectId: string | null;
}

/**
 * The queries one change makes stale. `mock_data`'s `id` is the checklist module id,
 * because mock data is keyed by module.
 */
export function keysToInvalidate(payload: InvalidatePayload): QueryKey[] {
  switch (payload.kind) {
    case "project":
      return [keys.projects.all];
    case "checklist_module":
      return [
        keys.checklistModules.detail(payload.id),
        keys.checklistModules.all,
        keys.checklistChangeSets.forModule(payload.id),
      ];
    case "mock_data":
      return [keys.mockData.detail(payload.id), keys.mockDataChangeSets.forModule(payload.id)];
    case "notification":
      return [keys.notifications.all];
  }
}

/**
 * Every live query, for `ready` and `resync`. `mockData` and `mockDataChangeSets` have no
 * `.all` key, so their prefixes are spelled here — the same arrays their `detail`/`forModule`
 * keys start with.
 */
export const ALL_LIVE_KEYS: QueryKey[] = [
  keys.projects.all,
  keys.checklistModules.all,
  keys.checklistChangeSets.all,
  ["mock-data"],
  ["mock-data-change-sets"],
  keys.notifications.all,
];

import type { QueryKey } from "@tanstack/react-query";

import { keys } from "@/lib/query/keys";

export type LiveKind =
  | "project"
  | "checklist_module"
  | "mock_data"
  | "notification"
  | "eval_set"
  | "eval_run";

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
      return [
        keys.mockData.detail(payload.id),
        keys.mockDataChangeSets.forModule(payload.id),
      ];
    case "eval_set":
      // `projectId` is the set's project; a payload without one cannot name the list.
      return [
        ...(payload.projectId ? [keys.eval.sets(payload.projectId)] : []),
        keys.eval.set(payload.id),
      ];
    case "eval_run":
      return [
        keys.eval.run(payload.id),
        keys.eval.allRuns,
        ...(payload.projectId ? [keys.eval.sets(payload.projectId)] : []),
      ];
    case "notification":
      return [keys.notifications.all];
    default:
      // An event kind this build does not know about — a newer server talking to an
      // older tab. Nothing to invalidate rather than a runtime crash on the switch.
      return [];
  }
}

/**
 * Whether `data` is shaped enough to be an `InvalidatePayload` — just `kind` and `id`,
 * since that is all `keysToInvalidate` reads. An `invalidate` event that fails this
 * check is ignored rather than handed to `keysToInvalidate`, which cannot itself guard
 * against a payload that is not an object at all.
 */
export function isInvalidatePayload(data: unknown): data is InvalidatePayload {
  return (
    typeof data === "object" &&
    data !== null &&
    typeof (data as { kind?: unknown }).kind === "string" &&
    typeof (data as { id?: unknown }).id === "string"
  );
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
  keys.eval.all,
];

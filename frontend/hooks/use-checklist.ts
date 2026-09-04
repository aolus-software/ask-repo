"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type {
  ChecklistChangeSetResponse,
  ChecklistModuleDetailResponse,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/**
 * One module with its grid.
 *
 * Polls only while a generation is running, and never in a backgrounded tab: a
 * generation takes minutes, and the screen has to notice the change set arriving
 * without the user reloading. Every other status is settled, so polling stops.
 */
export function useChecklistModule(moduleId: string) {
  return useQuery({
    queryKey: keys.checklistModules.detail(moduleId),
    queryFn: () =>
      apiFetch<ChecklistModuleDetailResponse>(
        endpoints.checklistModules.detail(moduleId),
      ),
    // Guards a caller that passes an id it does not have yet: without it an empty id
    // fires GET /checklist-modules/ and 404s on every render.
    enabled: Boolean(moduleId),
    refetchInterval: (query) =>
      query.state.data?.status === "generating" ? 3000 : false,
    refetchIntervalInBackground: false,
  });
}

/** A module's change sets, newest first. Fetched only when there is one to review. */
export function useModuleChangeSets(moduleId: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.checklistChangeSets.forModule(moduleId),
    queryFn: () =>
      apiFetch<ChecklistChangeSetResponse[]>(
        endpoints.checklistModules.changeSets(moduleId),
      ),
    enabled: Boolean(moduleId) && enabled,
  });
}

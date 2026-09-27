"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { checklistModuleListQueryString, endpoints } from "@/lib/api/endpoints";
import type {
  ChecklistChangeSetResponse,
  ChecklistModuleDetailResponse,
  ChecklistModuleListParams,
  ChecklistModuleResponse,
  PaginatedResponse,
} from "@/lib/api/types";
import { useLiveEvents } from "@/hooks/use-live-events";
import { keys } from "@/lib/query/keys";

/** The module list, alongside `useProjects`/`useUsers` (`docs/ui-audit-findings.md` §U3.2). */
export function useChecklistModules(params: ChecklistModuleListParams) {
  return useQuery({
    queryKey: keys.checklistModules.list(params),
    queryFn: () =>
      apiFetch<PaginatedResponse<ChecklistModuleResponse>>(
        `${endpoints.checklistModules.list}${checklistModuleListQueryString(params)}`,
      ),
  });
}

/**
 * One module with its grid.
 *
 * Polls only while a generation is running, and never in a backgrounded tab: a
 * generation takes minutes, and the screen has to notice the change set arriving
 * without the user reloading. Every other status is settled, so polling stops. The
 * interval is now a fallback and safety net for a lost live event: `connected` relaxes
 * it to a minute once `LiveEventsProvider` is delivering `invalidate` events itself.
 */
export function useChecklistModule(moduleId: string) {
  const { connected } = useLiveEvents();
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
      query.state.data?.status === "generating" ? (connected ? 60_000 : 3000) : false,
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

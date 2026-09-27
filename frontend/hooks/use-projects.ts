"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints, listQueryString } from "@/lib/api/endpoints";
import type { ListParams, PaginatedResponse, ProjectResponse } from "@/lib/api/types";
import { useLiveEvents } from "@/hooks/use-live-events";
import { keys } from "@/lib/query/keys";
import { isTerminalStatus } from "@/lib/status";

/**
 * Polls only while something is still moving, and the interval is now a fallback and
 * safety net for a lost live event rather than the primary way a status change is
 * noticed — `connected` (from `LiveEventsProvider`) relaxes it to a minute once the
 * live stream is delivering `invalidate` events itself. A backgrounded tab that polls
 * every three seconds for an hour is a defect, so `refetchIntervalInBackground` stays
 * off — refetch-on-focus already satisfies forms.md §10's "survives navigating away".
 */
export function useProjects(params: ListParams) {
  const { connected } = useLiveEvents();
  return useQuery({
    queryKey: keys.projects.list(params),
    queryFn: () =>
      apiFetch<PaginatedResponse<ProjectResponse>>(
        `${endpoints.projects.list}${listQueryString(params)}`,
      ),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const moving = items.some(
        (project) => !isTerminalStatus(project.status) || project.reindexInProgress,
      );
      return moving ? (connected ? 60_000 : 3000) : false;
    },
    refetchIntervalInBackground: false,
  });
}

export function useProject(id: string) {
  const { connected } = useLiveEvents();
  return useQuery({
    queryKey: keys.projects.detail(id),
    queryFn: () => apiFetch<ProjectResponse>(endpoints.projects.detail(id)),
    // Guards callers that pass an id they may not have yet — without it an empty id
    // fires GET /projects/ and 404s on every render of the component holding it.
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const project = query.state.data;
      if (!project) return false;
      return !isTerminalStatus(project.status) || project.reindexInProgress
        ? connected
          ? 60_000
          : 3000
        : false;
    },
    refetchIntervalInBackground: false,
  });
}

"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type {
  MockDataChangeSetResponse,
  MockDataDatasetDetailResponse,
} from "@/lib/api/types";
import { useLiveEvents } from "@/hooks/use-live-events";
import { keys } from "@/lib/query/keys";

/**
 * A module's mock dataset. Polls only while a generation is running — the interval is
 * a fallback and safety net for a lost live event: `connected` relaxes it to a minute
 * once `LiveEventsProvider` is delivering `invalidate` events itself.
 */
export function useMockDataDataset(moduleId: string) {
  const { connected } = useLiveEvents();
  return useQuery({
    queryKey: keys.mockData.detail(moduleId),
    queryFn: () =>
      apiFetch<MockDataDatasetDetailResponse>(endpoints.mockData.detail(moduleId)),
    enabled: Boolean(moduleId),
    refetchInterval: (query) =>
      query.state.data?.status === "generating" ? (connected ? 60_000 : 3000) : false,
    refetchIntervalInBackground: false,
  });
}

/** A dataset's change sets, fetched only when there is one to review. */
export function useMockDataChangeSets(moduleId: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.mockDataChangeSets.forModule(moduleId),
    queryFn: () =>
      apiFetch<MockDataChangeSetResponse[]>(endpoints.mockData.changeSets(moduleId)),
    enabled: Boolean(moduleId) && enabled,
  });
}

"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type {
  MockDataChangeSetResponse,
  MockDataDatasetDetailResponse,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/** A module's mock dataset. Polls only while a generation is running. */
export function useMockDataDataset(moduleId: string) {
  return useQuery({
    queryKey: keys.mockData.detail(moduleId),
    queryFn: () =>
      apiFetch<MockDataDatasetDetailResponse>(endpoints.mockData.detail(moduleId)),
    enabled: Boolean(moduleId),
    refetchInterval: (query) =>
      query.state.data?.status === "generating" ? 3000 : false,
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

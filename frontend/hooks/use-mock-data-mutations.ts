"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { MockDataDatasetResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

export function useGenerateMockData(moduleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (count: number) =>
      apiFetch<MockDataDatasetResponse>(endpoints.mockData.generate(moduleId), {
        method: "POST",
        body: JSON.stringify({ count }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.mockData.detail(moduleId) });
    },
  });
}

export function useDeleteMockDataRecord(moduleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (recordId: string) =>
      apiFetch<void>(endpoints.mockDataRecords.detail(recordId), { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.mockData.detail(moduleId) });
    },
  });
}

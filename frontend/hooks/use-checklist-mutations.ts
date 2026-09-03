"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type {
  ChecklistItemResponse,
  ChecklistItemStatus,
  ChecklistModuleDetailResponse,
  ChecklistModuleResponse,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

function useChecklistModuleInvalidation() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: keys.checklistModules.all });
}

export function useCreateChecklistModule() {
  const invalidate = useChecklistModuleInvalidation();
  return useMutation({
    mutationFn: (input: { projectId: string; name: string; sourcePath: string }) =>
      apiFetch<ChecklistModuleResponse>(endpoints.checklistModules.list, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: invalidate,
  });
}

export function useUpdateChecklistModule(id: string) {
  const invalidate = useChecklistModuleInvalidation();
  return useMutation({
    mutationFn: (input: { name?: string; sourcePath?: string }) =>
      apiFetch<ChecklistModuleResponse>(endpoints.checklistModules.detail(id), {
        method: "PATCH",
        body: JSON.stringify(input),
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteChecklistModule(id: string) {
  const invalidate = useChecklistModuleInvalidation();
  return useMutation({
    mutationFn: () =>
      apiFetch<void>(endpoints.checklistModules.detail(id), { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useGenerateChecklistModule(id: string) {
  const invalidate = useChecklistModuleInvalidation();
  return useMutation({
    mutationFn: () =>
      apiFetch<ChecklistModuleResponse>(endpoints.checklistModules.generate(id), {
        method: "POST",
      }),
    onSuccess: invalidate,
  });
}

export function useSaveChecklistItemResult(moduleId: string) {
  const queryClient = useQueryClient();
  const detailKey = keys.checklistModules.detail(moduleId);

  return useMutation({
    mutationFn: (input: {
      itemId: string;
      currentResult: string | null;
      status: ChecklistItemStatus;
    }) =>
      apiFetch<ChecklistItemResponse>(endpoints.checklistItems.result(input.itemId), {
        method: "PUT",
        body: JSON.stringify({
          currentResult: input.currentResult,
          status: input.status,
        }),
      }),
    // Optimistic on purpose, and only here: a tester works down twenty rows in one
    // sitting, and a round trip before each row settles makes the grid feel broken.
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: detailKey });
      const previous =
        queryClient.getQueryData<ChecklistModuleDetailResponse>(detailKey);
      if (previous) {
        queryClient.setQueryData<ChecklistModuleDetailResponse>(detailKey, {
          ...previous,
          items: previous.items.map((item) =>
            item.id === input.itemId
              ? { ...item, currentResult: input.currentResult, status: input.status }
              : item,
          ),
        });
      }
      return { previous };
    },
    onError: (_error, _input, context) => {
      // Rolled back rather than left showing a result the server never took.
      if (context?.previous) queryClient.setQueryData(detailKey, context.previous);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: detailKey });
      queryClient.invalidateQueries({ queryKey: keys.checklistItems.all });
    },
  });
}

export function useUpdateChecklistItemDetail(moduleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      itemId: string;
      feature?: string;
      testName?: string;
      expectedResult?: string;
      notes?: string | null;
    }) => {
      const { itemId, ...changes } = input;
      return apiFetch<ChecklistItemResponse>(endpoints.checklistItems.detail(itemId), {
        method: "PATCH",
        body: JSON.stringify(changes),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: keys.checklistModules.detail(moduleId),
      });
      queryClient.invalidateQueries({ queryKey: keys.checklistItems.all });
    },
  });
}

export function useDeleteChecklistItem(moduleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (itemId: string) =>
      apiFetch<void>(endpoints.checklistItems.detail(itemId), { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: keys.checklistModules.detail(moduleId),
      });
      queryClient.invalidateQueries({ queryKey: keys.checklistItems.all });
    },
  });
}

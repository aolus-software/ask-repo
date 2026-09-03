"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { ChecklistModuleResponse } from "@/lib/api/types";
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

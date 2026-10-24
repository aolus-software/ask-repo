"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { Language } from "@/lib/i18n/languages";
import type { ProjectResponse, ReindexResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

function useProjectInvalidation() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: keys.projects.all });
}

export function useCreateProject() {
  const invalidate = useProjectInvalidation();
  return useMutation({
    mutationFn: (input: {
      repoUrl: string;
      branch: string;
      pat?: string;
      contentLanguage?: Language;
    }) =>
      apiFetch<ProjectResponse>(endpoints.projects.list, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: invalidate,
  });
}

export function useReindexProject(id: string) {
  const invalidate = useProjectInvalidation();
  return useMutation({
    mutationFn: () =>
      apiFetch<ReindexResponse>(endpoints.projects.reindex(id), { method: "POST" }),
    onSuccess: invalidate,
  });
}

export function useDeleteProject(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<void>(endpoints.projects.detail(id), { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.projects.all });
      // Deleting a project soft-deletes conversations against it, for every owner
      // (docs/PRD.md §4.2), so the conversation cache is stale too.
      void queryClient.invalidateQueries({ queryKey: keys.conversations.all });
    },
  });
}

export function useUpdateProjectContentLanguage(id: string) {
  const invalidate = useProjectInvalidation();
  return useMutation({
    mutationFn: (contentLanguage: Language) =>
      apiFetch<ProjectResponse>(endpoints.projects.detail(id), {
        method: "PATCH",
        body: JSON.stringify({ contentLanguage }),
      }),
    onSuccess: invalidate,
  });
}

"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { MemberResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/**
 * Every mutation invalidates this project's membership list, and the project itself:
 * granting, changing or revoking a role can change the *caller's own* effective
 * permissions on it (`ProjectResponse.permissions`), which is what the Members tab's
 * own gating reads.
 */
function useMemberInvalidation(projectId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: keys.members.forProject(projectId),
    });
    void queryClient.invalidateQueries({ queryKey: keys.projects.detail(projectId) });
  };
}

export function useAddMember(projectId: string) {
  const invalidate = useMemberInvalidation(projectId);
  return useMutation({
    mutationFn: (input: { userId: string; role: string }) =>
      apiFetch<MemberResponse>(endpoints.members.list(projectId), {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: invalidate,
  });
}

export function useChangeMemberRole(projectId: string, userId: string) {
  const invalidate = useMemberInvalidation(projectId);
  return useMutation({
    mutationFn: (input: { role: string }) =>
      apiFetch<MemberResponse>(endpoints.members.detail(projectId, userId), {
        method: "PATCH",
        body: JSON.stringify(input),
      }),
    onSuccess: invalidate,
  });
}

export function useRevokeMember(projectId: string, userId: string) {
  const invalidate = useMemberInvalidation(projectId);
  return useMutation({
    mutationFn: () =>
      apiFetch<void>(endpoints.members.detail(projectId, userId), { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

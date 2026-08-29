"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { UserResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/** Every mutation invalidates the resource's PREFIX, never a specific list key. */
function useUserInvalidation() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: keys.users.all });
}

export function useCreateUser() {
  const invalidate = useUserInvalidation();
  return useMutation({
    mutationFn: (input: { name: string; email: string; password: string; isAdmin: boolean }) =>
      apiFetch<UserResponse>(endpoints.users.list, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: invalidate,
  });
}

export function useUpdateUser(id: string) {
  const invalidate = useUserInvalidation();
  return useMutation({
    mutationFn: (input: { name?: string; isAdmin?: boolean }) =>
      apiFetch<UserResponse>(endpoints.users.detail(id), {
        method: "PATCH",
        body: JSON.stringify(input),
      }),
    onSuccess: invalidate,
  });
}

export function useResetPassword(id: string) {
  return useMutation({
    mutationFn: (input: { newPassword: string }) =>
      apiFetch<void>(endpoints.users.resetPassword(id), {
        method: "POST",
        body: JSON.stringify(input),
      }),
  });
}

export function useDeactivateUser(id: string) {
  const invalidate = useUserInvalidation();
  return useMutation({
    mutationFn: () => apiFetch<void>(endpoints.users.detail(id), { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { RoleResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/** Every mutation invalidates the resource's PREFIX, never a specific list key. */
function useRoleInvalidation() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: keys.roles.all });
}

export function useCreateRole() {
  const invalidate = useRoleInvalidation();
  return useMutation({
    mutationFn: (input: { name: string; description?: string }) =>
      apiFetch<RoleResponse>(endpoints.roles.list, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: invalidate,
  });
}

/**
 * Replaces the role's whole permission set — forms.md §8: an omitted id is a
 * revocation, not an untouched value, so the matrix always submits every checked
 * permission, never a diff.
 */
export function useUpdateRolePermissions(id: string) {
  const invalidate = useRoleInvalidation();
  return useMutation({
    mutationFn: (permissions: string[]) =>
      apiFetch<RoleResponse>(endpoints.roles.detail(id), {
        method: "PATCH",
        body: JSON.stringify({ permissions }),
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteRole(id: string) {
  const invalidate = useRoleInvalidation();
  return useMutation({
    mutationFn: () => apiFetch<void>(endpoints.roles.detail(id), { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

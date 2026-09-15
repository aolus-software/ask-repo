"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { PermissionCatalogResponse, RoleResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/**
 * Every role on the instance, system roles first (the API already orders them).
 *
 * `GET /roles` is admin-only (`backend/app/api/routes/roles.py`), so a caller that
 * cannot assume an administrator is asking — the add-member dialog, open to any
 * project owner — passes `enabled: false` rather than let this 403.
 */
export function useRoles({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: keys.roles.list,
    queryFn: () => apiFetch<RoleResponse[]>(endpoints.roles.list),
    enabled,
  });
}

/**
 * One role, by id. There is no `GET /roles/{id}` — roles are few enough that the
 * matrix page reads the same list the roles screen does and finds its row, so both
 * views share one cache entry rather than two.
 *
 * `notFound` is true only once the list has loaded successfully and no row matches —
 * distinct from `isLoading`/`isError`, which the caller checks first.
 */
export function useRole(id: string) {
  const query = useRoles();
  const role = query.data?.find((candidate) => candidate.id === id);
  const notFound = !query.isLoading && !query.isError && role === undefined;

  return { ...query, data: role, notFound };
}

/** The permission catalogue, grouped and labelled by the server for the matrix. */
export function usePermissionCatalog() {
  return useQuery({
    queryKey: keys.permissionCatalogue,
    queryFn: () => apiFetch<PermissionCatalogResponse>(endpoints.permissions.catalogue),
  });
}

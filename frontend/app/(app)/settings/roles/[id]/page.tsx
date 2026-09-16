import { HydrationBoundary, dehydrate } from "@tanstack/react-query";

import { RoleMatrixScreen } from "@/app/(app)/settings/roles/[id]/role-matrix-screen";
import { endpoints } from "@/lib/api/endpoints";
import { serverFetch } from "@/lib/api/server";
import type { PermissionCatalogResponse, RoleResponse } from "@/lib/api/types";
import { makeQueryClient } from "@/lib/query/client";
import { keys } from "@/lib/query/keys";

/** params is async in Next 16 and is always awaited. */
export default async function RoleMatrixPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  // There is no `GET /roles/{id}` — the matrix reads the same list the roles screen
  // does (`useRole`, `hooks/use-roles.ts`), so both prefetch and client share one
  // cache entry rather than the page inventing a second shape for one role.
  const queryClient = makeQueryClient();
  try {
    await Promise.all([
      queryClient.prefetchQuery({
        queryKey: keys.roles.list,
        queryFn: () => serverFetch<RoleResponse[]>(endpoints.roles.list),
      }),
      queryClient.prefetchQuery({
        queryKey: keys.permissionCatalogue,
        queryFn: () =>
          serverFetch<PermissionCatalogResponse>(endpoints.permissions.catalogue),
      }),
    ]);
  } catch {
    // Not fatal — the client refetches and renders NotFound or the error.
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <RoleMatrixScreen id={id} />
    </HydrationBoundary>
  );
}

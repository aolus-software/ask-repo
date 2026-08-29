import { HydrationBoundary, dehydrate } from "@tanstack/react-query";
import { Suspense } from "react";

import { ProjectsScreen } from "@/app/(app)/projects/projects-screen";
import { SORT, endpoints, listQueryString } from "@/lib/api/endpoints";
import { serverFetch } from "@/lib/api/server";
import type { ListParams, PaginatedResponse, ProjectResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";
import { makeQueryClient } from "@/lib/query/client";

/**
 * Prefetches the EXACT key the client screen will use, so the first paint has data
 * and no spinner. Both sides derive the key from `keys.ts`, which is what keeps them
 * honest. searchParams is awaited — it is async in Next 16.
 */
export default async function ProjectsPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string; search?: string }>;
}) {
  const resolved = await searchParams;
  const params: ListParams = {
    limit: 25,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
    page: Number(resolved.page ?? 1),
    search: resolved.search || undefined,
  };

  const queryClient = makeQueryClient();
  try {
    await queryClient.prefetchQuery({
      queryKey: keys.projects.list(params),
      queryFn: () =>
        serverFetch<PaginatedResponse<ProjectResponse>>(
          `${endpoints.projects.list}${listQueryString(params)}`,
        ),
    });
  } catch {
    // A prefetch failure is not fatal: the client refetches and renders the error.
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <Suspense>
        <ProjectsScreen />
      </Suspense>
    </HydrationBoundary>
  );
}

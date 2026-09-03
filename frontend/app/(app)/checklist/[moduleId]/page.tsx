import { HydrationBoundary, dehydrate } from "@tanstack/react-query";

import { ModuleScreen } from "@/app/(app)/checklist/[moduleId]/module-screen";
import { endpoints } from "@/lib/api/endpoints";
import { serverFetch } from "@/lib/api/server";
import type { ChecklistModuleDetailResponse } from "@/lib/api/types";
import { makeQueryClient } from "@/lib/query/client";
import { keys } from "@/lib/query/keys";

/** `params` is async in Next 16 and is always awaited. */
export default async function ModulePage({
  params,
}: {
  params: Promise<{ moduleId: string }>;
}) {
  const { moduleId } = await params;

  // Prefetched on the server so the first paint carries the grid, matching the project
  // detail page. The client refetches regardless, so a failure here is not fatal.
  const queryClient = makeQueryClient();
  try {
    await queryClient.prefetchQuery({
      queryKey: keys.checklistModules.detail(moduleId),
      queryFn: () =>
        serverFetch<ChecklistModuleDetailResponse>(
          endpoints.checklistModules.detail(moduleId),
        ),
    });
  } catch {
    // Not fatal — the client refetches and renders NotFound or the error.
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <ModuleScreen moduleId={moduleId} />
    </HydrationBoundary>
  );
}

import { HydrationBoundary, dehydrate } from "@tanstack/react-query";

import { ProjectDetailScreen } from "@/app/(app)/projects/[id]/project-detail-screen";
import { endpoints } from "@/lib/api/endpoints";
import { serverFetch } from "@/lib/api/server";
import type { ProjectResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";
import { makeQueryClient } from "@/lib/query/client";

/** params is async in Next 16 and is always awaited. */
export default async function ProjectDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  // Detail pages prefetch their own key, exactly as list pages do, so the first
  // paint has data instead of a skeleton.
  const queryClient = makeQueryClient();
  try {
    await queryClient.prefetchQuery({
      queryKey: keys.projects.detail(id),
      queryFn: () => serverFetch<ProjectResponse>(endpoints.projects.detail(id)),
    });
  } catch {
    // Not fatal — the client refetches and renders NotFound or the error.
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <ProjectDetailScreen id={id} />
    </HydrationBoundary>
  );
}

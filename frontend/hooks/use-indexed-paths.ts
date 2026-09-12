"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints, indexedPathsQueryString } from "@/lib/api/endpoints";
import type { IndexedPathsResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/**
 * One level of a project's indexed tree, or a search's matches across all of it.
 *
 * Disabled without a project id: the create dialog renders the picker before a project
 * is chosen, and firing `GET /projects//indexed-paths` on every keystroke until then
 * would 404 in a loop.
 *
 * The server caches per (project, generation), so expanding back into a directory
 * already visited costs nothing there either — no need for a long `staleTime` here.
 */
export function useIndexedPaths(
  projectId: string,
  params: { path?: string; search?: string },
) {
  return useQuery({
    queryKey: keys.projects.indexedPaths(projectId, params),
    queryFn: () =>
      apiFetch<IndexedPathsResponse>(
        `${endpoints.projects.indexedPaths(projectId)}${indexedPathsQueryString(params)}`,
      ),
    enabled: Boolean(projectId),
    // A tree only moves on a reindex, and the response names the generation it came
    // from, so refetching on every focus buys nothing.
    refetchOnWindowFocus: false,
  });
}

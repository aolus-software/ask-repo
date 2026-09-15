"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { MemberResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/** Everyone with a role on this project. Requires `membership.read`, which every role holds. */
export function useMembers(projectId: string, enabled = true) {
  return useQuery({
    queryKey: keys.members.forProject(projectId),
    queryFn: () => apiFetch<MemberResponse[]>(endpoints.members.list(projectId)),
    enabled: Boolean(projectId) && enabled,
  });
}

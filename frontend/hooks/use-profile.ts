"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints, listQueryString } from "@/lib/api/endpoints";
import type {
  ActivityEntry,
  ListParams,
  MembershipSummary,
  PaginatedResponse,
  SessionSummary,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/** None of these poll: a profile is read when opened, and refetched after a change. */
export function useMemberships() {
  return useQuery({
    queryKey: keys.profile.memberships,
    queryFn: () => apiFetch<MembershipSummary[]>(endpoints.me.memberships),
  });
}

export function useSessions() {
  return useQuery({
    queryKey: keys.profile.sessions,
    queryFn: () => apiFetch<SessionSummary[]>(endpoints.me.sessions),
  });
}

export function useRevokeSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(endpoints.me.session(id), { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.profile.sessions }),
  });
}

export function useActivity(params: ListParams) {
  return useQuery({
    queryKey: keys.profile.activity(params),
    queryFn: () =>
      apiFetch<PaginatedResponse<ActivityEntry>>(
        `${endpoints.me.activity}${listQueryString(params)}`,
      ),
    placeholderData: keepPreviousData,
  });
}

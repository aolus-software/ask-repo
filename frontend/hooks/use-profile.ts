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
  AnswerStyle,
  LanguageSetting,
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
    mutationFn: (id: string) =>
      apiFetch<void>(endpoints.me.session(id), { method: "DELETE" }),
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

export function useAnswerStyle() {
  return useQuery({
    queryKey: keys.profile.answerStyle,
    queryFn: () => apiFetch<AnswerStyle>(endpoints.me.answerStyle),
  });
}

/** Replaces all three dials; the backend requires every key. */
export function useUpdateAnswerStyle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (style: AnswerStyle) =>
      apiFetch<AnswerStyle>(endpoints.me.answerStyle, {
        method: "PUT",
        body: JSON.stringify(style),
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.profile.answerStyle }),
  });
}

export function useLanguage() {
  return useQuery({
    queryKey: keys.profile.language,
    queryFn: () => apiFetch<LanguageSetting>(endpoints.me.language),
  });
}

/**
 * Store the caller's language. The API proxy mirrors it onto the locale cookie from
 * the response; the caller then refreshes the route so Server Components re-render
 * in the new language.
 */
export function useUpdateLanguage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (setting: LanguageSetting) =>
      apiFetch<LanguageSetting>(endpoints.me.language, {
        method: "PUT",
        body: JSON.stringify(setting),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.profile.language }),
  });
}

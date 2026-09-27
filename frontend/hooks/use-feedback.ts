"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints, feedbackListQueryString } from "@/lib/api/endpoints";
import type {
  FeedbackAdminRead,
  FeedbackListParams,
  FeedbackSummary,
  PaginatedResponse,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

export function useFeedbackList(params: FeedbackListParams) {
  return useQuery({
    queryKey: keys.feedback.list(params),
    queryFn: () =>
      apiFetch<PaginatedResponse<FeedbackAdminRead>>(
        `${endpoints.feedback.list}${feedbackListQueryString(params)}`,
      ),
  });
}

/** The summary ignores pagination; only the filters shape it. */
export function useFeedbackSummary(params: Partial<FeedbackListParams>) {
  const { page: _page, limit: _limit, search: _search, ...filters } = params;
  return useQuery({
    queryKey: keys.feedback.summary(filters),
    queryFn: () =>
      apiFetch<FeedbackSummary>(`${endpoints.feedback.summary}${feedbackListQueryString(filters)}`),
  });
}

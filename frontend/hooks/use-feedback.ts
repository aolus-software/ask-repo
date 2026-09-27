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

/** The summary ignores pagination; only the filters shape it. Named field-by-field
 * rather than destructuring-and-discarding `page`/`limit`/`search`, so nothing is
 * bound and then thrown away unused. An omitted filter lands as `undefined`, which
 * `JSON.stringify` (what the query-key hash goes through) drops the same as an
 * absent key, so the cache key is unchanged either way. */
export function useFeedbackSummary(params: Partial<FeedbackListParams>) {
  const filters: Partial<FeedbackListParams> = {
    projectId: params.projectId,
    feature: params.feature,
    rating: params.rating,
    reasonCode: params.reasonCode,
    promptVersion: params.promptVersion,
    createdFrom: params.createdFrom,
    createdTo: params.createdTo,
  };

  return useQuery({
    queryKey: keys.feedback.summary(filters),
    queryFn: () =>
      apiFetch<FeedbackSummary>(
        `${endpoints.feedback.summary}${feedbackListQueryString(filters)}`,
      ),
  });
}

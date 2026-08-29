"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints, listQueryString } from "@/lib/api/endpoints";
import type {
  ConversationDetailResponse,
  ConversationResponse,
  ListParams,
  PaginatedResponse,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/** Always the caller's own — there is no "all conversations" view (docs/PRD.md §4.2). */
export function useConversations(params: ListParams & { projectId?: string }) {
  return useQuery({
    queryKey: keys.conversations.list(params),
    queryFn: () => {
      const { projectId, ...rest } = params;
      const qs = listQueryString(rest);
      const suffix = projectId ? `${qs ? `${qs}&` : "?"}projectId=${projectId}` : qs;
      return apiFetch<PaginatedResponse<ConversationResponse>>(
        `${endpoints.conversations.list}${suffix}`,
      );
    },
  });
}

export function useConversation(id: string) {
  return useQuery({
    queryKey: keys.conversations.detail(id),
    queryFn: () => apiFetch<ConversationDetailResponse>(endpoints.conversations.detail(id)),
    enabled: Boolean(id),
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { projectId: string }) =>
      apiFetch<ConversationResponse>(endpoints.conversations.list, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.conversations.all }),
  });
}

export function useDeleteConversation(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>(endpoints.conversations.detail(id), { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.conversations.all }),
  });
}

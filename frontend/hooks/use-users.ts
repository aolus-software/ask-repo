"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints, listQueryString } from "@/lib/api/endpoints";
import type { ListParams, PaginatedResponse, UserResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

export function useUsers(params: ListParams) {
  return useQuery({
    queryKey: keys.users.list(params),
    queryFn: () =>
      apiFetch<PaginatedResponse<UserResponse>>(`${endpoints.users.list}${listQueryString(params)}`),
  });
}

"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { auditEventListQueryString, endpoints } from "@/lib/api/endpoints";
import type { AuditEventListParams, AuditEventSummary, PaginatedResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

export function useAuditEvents(params: AuditEventListParams) {
  return useQuery({
    queryKey: keys.auditEvents.list(params),
    queryFn: () =>
      apiFetch<PaginatedResponse<AuditEventSummary>>(
        `${endpoints.auditEvents.list}${auditEventListQueryString(params)}`,
      ),
  });
}

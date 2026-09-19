"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { auditEventListQueryString, endpoints } from "@/lib/api/endpoints";
import type {
  AuditEventListParams,
  AuditEventResponse,
  AuditEventSummary,
  PaginatedResponse,
} from "@/lib/api/types";
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

/** One event, by id — the detail screen's `GET /audit-events/{id}`. */
export function useAuditEvent(id: string) {
  return useQuery({
    queryKey: keys.auditEvents.detail(id),
    queryFn: () => apiFetch<AuditEventResponse>(endpoints.auditEvents.detail(id)),
    // Guards a caller that does not have the id yet — without it an empty id fires
    // GET /audit-events/ and 404s on every render of the component holding it.
    enabled: Boolean(id),
  });
}

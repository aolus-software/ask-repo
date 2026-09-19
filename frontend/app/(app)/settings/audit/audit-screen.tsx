"use client";

import { ScrollText } from "lucide-react";

import { AuditFilters } from "@/components/audit/audit-filters";
import { AuditTable } from "@/components/audit/audit-table";
import { EmptyState } from "@/components/feedback/empty-state";
import { Forbidden } from "@/components/feedback/forbidden";
import { ListError } from "@/components/feedback/list-error";
import { ListToolbar } from "@/components/layout/list-toolbar";
import { PageHeader } from "@/components/layout/page-header";
import { PaginationFooter } from "@/components/layout/pagination-footer";
import { Card } from "@/components/ui/card";
import { useAuditEvents } from "@/hooks/use-audit-events";
import { useListParams } from "@/hooks/use-list-params";
import { useSession } from "@/hooks/use-session";
import type { AuditEventListParams } from "@/lib/api/types";

const EXTRA_PARAMS = ["eventType", "outcome", "occurredFrom", "occurredTo"] as const;

/**
 * `setParam` reads the current URL on every call, so firing it once per changed key
 * would have each call clobber the one before it within the same event handler.
 * `AuditFilters` only ever changes one field per interaction, so diffing against the
 * params already on the URL and writing the single key that moved keeps this to one
 * `setParam` call per change.
 */
function changedKey(
  next: Partial<AuditEventListParams>,
  current: Partial<AuditEventListParams>,
): (typeof EXTRA_PARAMS)[number] | undefined {
  return EXTRA_PARAMS.find((key) => next[key] !== current[key]);
}

export function AuditScreen() {
  const user = useSession();
  const { params, searchInput, setSearch, setPage, setParam } = useListParams(
    { limit: 25 },
    { extraParams: EXTRA_PARAMS },
  );
  const listParams = params as AuditEventListParams;
  const query = useAuditEvents(listParams);
  const events = query.data?.items ?? [];

  // The route body is wrapped in its gate. Hiding the nav item is not gating the
  // route — an operator can type the URL (navigation.md §6). This mirrors the
  // backend's ADMIN_REQUIRED; it does not replace it.
  if (!user.isAdmin)
    return <Forbidden message="Only administrators can read the audit trail." />;

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="Audit trail"
        description="Every write and export on this instance, newest first."
      />

      <ListToolbar
        initialSearch={searchInput}
        placeholder="Search actor, target or address"
        onSearchChange={setSearch}
        // Search plus four filters, so the row needs a fifth cell -- at the default
        // four the dates wrap onto a line of their own.
        columns={5}
        filters={
          <AuditFilters
            currentFilters={listParams}
            onFiltersChange={(filters) => {
              const key = changedKey(filters, listParams);
              if (key) setParam(key, filters[key]);
            }}
          />
        }
      />

      <Card className="p-0">
        {query.isError ? (
          <div className="p-6">
            <ListError error={query.error} onRetry={() => query.refetch()} />
          </div>
        ) : !query.isLoading && events.length === 0 ? (
          <EmptyState
            icon={ScrollText}
            title={listParams.search ? "No events match" : "No events yet"}
            description={
              listParams.search
                ? "Try a different search or a wider date range."
                : "Writes and exports on this instance will appear here."
            }
          />
        ) : (
          <>
            <AuditTable events={events} isLoading={query.isLoading} />
            <PaginationFooter
              page={query.data?.page ?? 1}
              totalPages={query.data?.totalPages ?? 1}
              totalCount={query.data?.totalCount ?? 0}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>
    </div>
  );
}

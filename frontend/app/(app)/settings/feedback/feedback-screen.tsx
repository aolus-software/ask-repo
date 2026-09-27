"use client";

import { MessageSquareWarning } from "lucide-react";

import { EmptyState } from "@/components/feedback/empty-state";
import { Forbidden } from "@/components/feedback/forbidden";
import { ListError } from "@/components/feedback/list-error";
import { ListToolbar } from "@/components/layout/list-toolbar";
import { PageHeader } from "@/components/layout/page-header";
import { PaginationFooter } from "@/components/layout/pagination-footer";
import { FeedbackFilters } from "@/components/output-feedback/feedback-filters";
import {
  FeedbackSummary,
  FeedbackSummarySkeleton,
} from "@/components/output-feedback/feedback-summary";
import { FeedbackTable } from "@/components/output-feedback/feedback-table";
import { Card } from "@/components/ui/card";
import { useFeedbackList, useFeedbackSummary } from "@/hooks/use-feedback";
import { useListParams } from "@/hooks/use-list-params";
import { useSession } from "@/hooks/use-session";
import type { FeedbackListParams } from "@/lib/api/types";

const EXTRA_PARAMS = [
  "projectId",
  "feature",
  "rating",
  "reasonCode",
  "promptVersion",
  "createdFrom",
  "createdTo",
] as const;

function changedKey(
  next: Partial<FeedbackListParams>,
  current: Partial<FeedbackListParams>,
): (typeof EXTRA_PARAMS)[number] | undefined {
  return EXTRA_PARAMS.find((key) => next[key] !== current[key]);
}

export function FeedbackScreen() {
  const user = useSession();
  const { params, setPage, setParam } = useListParams(
    { limit: 25 },
    { extraParams: EXTRA_PARAMS },
  );
  const listParams = params as FeedbackListParams;
  const list = useFeedbackList(listParams);
  const summary = useFeedbackSummary(listParams);
  const rows = list.data?.items ?? [];

  if (!user.isAdmin)
    return (
      <Forbidden message="Only administrators can read feedback on model output." />
    );

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6">
      <PageHeader
        title="Feedback"
        description="How people rated answers, chat replies and proposals. Who voted, and the question behind a vote, are never shown."
      />

      <ListToolbar
        columns={5}
        filters={
          <FeedbackFilters
            currentFilters={listParams}
            onFiltersChange={(filters) => {
              const key = changedKey(filters, listParams);
              if (key) setParam(key, filters[key]);
            }}
          />
        }
      />

      {summary.isError ? (
        <ListError error={summary.error} onRetry={() => summary.refetch()} />
      ) : summary.isLoading ? (
        <FeedbackSummarySkeleton />
      ) : summary.data ? (
        <FeedbackSummary summary={summary.data} />
      ) : null}

      <Card className="p-0">
        {list.isError ? (
          <div className="p-6">
            <ListError error={list.error} onRetry={() => list.refetch()} />
          </div>
        ) : !list.isLoading && rows.length === 0 ? (
          <EmptyState
            icon={MessageSquareWarning}
            title="No feedback yet"
            description="Votes on answers, chat replies and change sets will appear here."
          />
        ) : (
          <>
            <FeedbackTable rows={rows} isLoading={list.isLoading} />
            <PaginationFooter
              page={list.data?.page ?? 1}
              totalPages={list.data?.totalPages ?? 1}
              totalCount={list.data?.totalCount ?? 0}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>
    </div>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { ListToolbar } from "@/components/layout/list-toolbar";
import { PageHeader } from "@/components/layout/page-header";
import { PaginationFooter } from "@/components/layout/pagination-footer";
import { QAFilters } from "@/components/qa/qa-filters";
import { QATable } from "@/components/qa/qa-table";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useProjects } from "@/hooks/use-projects";
import { apiFetch } from "@/lib/api/client";
import { SORT, qaListQueryString, endpoints } from "@/lib/api/endpoints";
import type { PaginatedResponse, QAListParams, QAPairResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

const DEFAULTS = {
  limit: 25,
  sort: SORT.qaPairs.updatedAt,
  sortDirection: "desc" as const,
};

/**
 * URL state for the whole grid — search, page, and the six filters — behind one
 * `update(patch)`. Modelled on `hooks/use-list-params.ts`, widened for the extra
 * filters `QAFilters` needs: any change other than an explicit page resets to page 1,
 * the same rule `setSearch` there already follows, so a stale filter never leaves the
 * caller looking at page 4 of a result set that now has one page.
 */
function useQAListParams() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [searchInput] = useState(searchParams.get("search") ?? "");

  const params = useMemo<QAListParams>(() => {
    const get = (key: string) => searchParams.get(key) ?? undefined;
    return {
      ...DEFAULTS,
      page: Number(searchParams.get("page") ?? 1),
      search: get("search"),
      projectId: get("projectId"),
      module: get("module"),
      tag: get("tag"),
      source: get("source") as QAListParams["source"],
      status: get("status") as QAListParams["status"],
      createdBy: get("createdBy"),
    };
  }, [searchParams]);

  const update = useCallback(
    (patch: Partial<QAListParams>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(patch)) {
        if (key === "page") continue;
        if (value === undefined || value === "") next.delete(key);
        else next.set(key, String(value));
      }
      if (patch.page && patch.page > 1) next.set("page", String(patch.page));
      else next.delete("page");
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const setSearch = useCallback(
    (value: string) => update({ search: value || undefined }),
    [update],
  );
  const setPage = useCallback((page: number) => update({ page }), [update]);

  return { params, searchInput, setSearch, setPage, update };
}

export function QAScreen() {
  const { params, searchInput, setSearch, setPage, update } = useQAListParams();

  const query = useQuery({
    queryKey: keys.qaPairs.list(params),
    queryFn: () =>
      apiFetch<PaginatedResponse<QAPairResponse>>(
        `${endpoints.qaPairs.list}${qaListQueryString(params)}`,
      ),
  });
  const pairs = query.data?.items ?? [];

  // Same page of projects the filter bar's Select fetches — the query key matches, so
  // this shares that cache entry rather than issuing a second request.
  const projects = useProjects({
    limit: 100,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
  });
  const projectNames = useMemo(
    () =>
      new Map(
        (projects.data?.items ?? []).map((project) => [project.id, project.name]),
      ),
    [projects.data],
  );

  const isFiltered = Boolean(
    params.search ||
    params.projectId ||
    params.module ||
    params.tag ||
    params.source ||
    params.status ||
    params.createdBy,
  );

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="QA List"
        description="Answers the instance has published and verified. Anyone here can read or review one."
      />

      <ListToolbar
        initialSearch={searchInput}
        placeholder="Search questions"
        onSearchChange={setSearch}
        filters={<QAFilters params={params} onChange={update} />}
      />

      <Card className="p-0">
        {!query.isLoading && pairs.length === 0 ? (
          <EmptyState
            icon={ClipboardCheck}
            title={isFiltered ? "No QA pairs match" : "No QA pairs yet"}
            description="Save an answer from a conversation in Ask to start building a shared, reviewable record."
            action={
              isFiltered ? undefined : (
                <Button render={<Link href="/ask" />}>Ask a question</Button>
              )
            }
          />
        ) : (
          <>
            <QATable
              pairs={pairs}
              isLoading={query.isLoading}
              projectNames={projectNames}
            />
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

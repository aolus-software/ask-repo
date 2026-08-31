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
 * Mirrors the backend's `qa_export_max_rows` default (`backend/app/config.py`,
 * `QA_EXPORT_MAX_ROWS` in `backend/.env.example`). Nothing on the wire exposes an
 * operator override of that setting to the client, so this only matches the cap
 * the server actually enforces on an unmodified instance — it disables the button
 * on the same threshold `QAPairService.export` would refuse at by default, per
 * design spec §6.2. An operator who raises `QA_EXPORT_MAX_ROWS` gets a button that
 * disables too early rather than too late, which is the safe direction to drift:
 * exceeding a cap this constant does not know about still fails safely server-side
 * with `409 EXPORT_TOO_LARGE` rather than a corrupted download.
 */
const QA_EXPORT_MAX_ROWS = 5000;

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
  const totalCount = query.data?.totalCount ?? 0;
  // The route builds the whole workbook in memory before refusing, so the button
  // is disabled below what the server would 409 on rather than after the click
  // (design spec §6.2) — narrowing the filters is the only recovery either way.
  const overExportCap = totalCount > QA_EXPORT_MAX_ROWS;
  const exportDisabled = query.isLoading || totalCount === 0 || overExportCap;

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
        action={
          <div className="flex items-center gap-3">
            <span className="text-muted-foreground text-sm">
              {totalCount} {totalCount === 1 ? "pair" : "pairs"}
              {overExportCap
                ? ` — narrow the filters to export (cap ${QA_EXPORT_MAX_ROWS})`
                : ""}
            </span>
            {/* Same-origin, so the session cookies ride along and the browser
                handles the download — no blob assembly, no object URLs (design
                spec §6.4, §7.1). Rendered as a plain disabled Button rather than
                a disabled anchor above the cap: an anchor's `disabled` attribute
                has no browser meaning, so a click would still navigate to the
                409 error page this button exists to keep the operator from
                seeing. */}
            {exportDisabled ? (
              <Button variant="outline" disabled>
                Export
              </Button>
            ) : (
              <Button
                variant="outline"
                render={
                  <a
                    href={`/api/qa-pairs/export${qaListQueryString(params)}`}
                    download
                  />
                }
              >
                Export
              </Button>
            )}
          </div>
        }
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

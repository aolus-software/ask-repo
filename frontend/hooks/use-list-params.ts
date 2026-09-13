"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import type { ListParams } from "@/lib/api/types";

/** A stable empty array, so an omitted `extraParams` does not create a fresh array
 * identity — and re-trigger the memo below — on every render. */
const NO_EXTRA_PARAMS: readonly string[] = [];

/**
 * Reads list state from the URL so a page is shareable and survives a reload, and
 * writes it back with replace() so paging does not fill the history stack.
 *
 * `extraParams` names additional query-string keys (e.g. `projectId`) that a screen
 * filters by beyond the common `search`/`page` pair — added so a screen with its own
 * filter does not have to reimplement this hook from scratch
 * (`docs/ui-audit-findings.md` §U3.2). Each named key is read into `params` and
 * written back through `setParam`, following the same reset-page-on-change rule as
 * `setSearch`.
 */
export function useListParams(
  defaults: ListParams,
  options?: { extraParams?: readonly string[] },
) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const extraParams = options?.extraParams ?? NO_EXTRA_PARAMS;

  const urlSearch = searchParams.get("search") ?? "";
  const [searchInput] = useState(urlSearch);

  const { limit, sort, sortDirection } = defaults;

  // `extraParams` should be a module-level constant at the call site (see
  // `checklist-screen.tsx`'s `EXTRA_PARAMS`) so this memoises across renders instead
  // of recomputing every time on a fresh inline array.
  const extraValues = useMemo(() => {
    const result: Record<string, string | undefined> = {};
    for (const key of extraParams) result[key] = searchParams.get(key) ?? undefined;
    return result;
  }, [searchParams, extraParams]);

  const params = useMemo<ListParams>(
    () => ({
      limit,
      sort,
      sortDirection,
      page: Number(searchParams.get("page") ?? 1),
      search: urlSearch || undefined,
      ...extraValues,
    }),
    [limit, sort, sortDirection, searchParams, urlSearch, extraValues],
  );

  const write = useCallback(
    (next: URLSearchParams) => {
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  const setSearch = useCallback(
    (value: string) => {
      const next = new URLSearchParams(searchParams.toString());
      if (value) next.set("search", value);
      else next.delete("search");
      // Any new filter resets to the first page — page 4 of a different result set
      // is almost always empty.
      next.delete("page");
      write(next);
    },
    [searchParams, write],
  );

  const setPage = useCallback(
    (page: number) => {
      const next = new URLSearchParams(searchParams.toString());
      if (page > 1) next.set("page", String(page));
      else next.delete("page");
      write(next);
    },
    [searchParams, write],
  );

  const setParam = useCallback(
    (key: string, value: string | undefined) => {
      const next = new URLSearchParams(searchParams.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      next.delete("page");
      write(next);
    },
    [searchParams, write],
  );

  return { params, searchInput, setSearch, setPage, setParam };
}

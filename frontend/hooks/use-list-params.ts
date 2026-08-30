"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import type { ListParams } from "@/lib/api/types";

/**
 * Reads list state from the URL so a page is shareable and survives a reload, and
 * writes it back with replace() so paging does not fill the history stack.
 */
export function useListParams(defaults: ListParams) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const urlSearch = searchParams.get("search") ?? "";
  const [searchInput] = useState(urlSearch);

  const { limit, sort, sortDirection } = defaults;

  const params = useMemo<ListParams>(
    () => ({
      limit,
      sort,
      sortDirection,
      page: Number(searchParams.get("page") ?? 1),
      search: urlSearch || undefined,
    }),
    [limit, sort, sortDirection, searchParams, urlSearch],
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

  return { params, searchInput, setSearch, setPage };
}

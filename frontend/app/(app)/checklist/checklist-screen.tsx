"use client";

import { useCallback } from "react";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Plus } from "lucide-react";

import { CreateModuleDialog } from "@/components/checklist/create-module-dialog";
import { ModuleFilters } from "@/components/checklist/module-filters";
import { ModuleTable } from "@/components/checklist/module-table";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListToolbar } from "@/components/layout/list-toolbar";
import { PageHeader } from "@/components/layout/page-header";
import { PaginationFooter } from "@/components/layout/pagination-footer";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api/client";
import { checklistModuleListQueryString, endpoints } from "@/lib/api/endpoints";
import type {
  ChecklistModuleListParams,
  ChecklistModuleResponse,
  PaginatedResponse,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";
import { useState } from "react";

export function ChecklistScreen() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [creating, setCreating] = useState(false);

  const params: ChecklistModuleListParams = {
    page: Number(searchParams.get("page") ?? 1),
    limit: 25,
    search: searchParams.get("search") ?? undefined,
    projectId: searchParams.get("projectId") ?? undefined,
  };

  const { data, isPending } = useQuery({
    queryKey: keys.checklistModules.list(params),
    queryFn: () =>
      apiFetch<PaginatedResponse<ChecklistModuleResponse>>(
        `${endpoints.checklistModules.list}${checklistModuleListQueryString(params)}`,
      ),
  });

  const modules = data?.items ?? [];

  const handleSearch = useCallback(
    (value: string) => {
      const next = new URLSearchParams(searchParams.toString());
      if (value) next.set("search", value);
      else next.delete("search");
      next.delete("page");
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [searchParams, router, pathname],
  );

  const handleProjectChange = useCallback(
    (projectId: string | undefined) => {
      const next = new URLSearchParams(searchParams.toString());
      if (projectId) next.set("projectId", projectId);
      else next.delete("projectId");
      next.delete("page");
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [searchParams, router, pathname],
  );

  const handlePageChange = useCallback(
    (page: number) => {
      const next = new URLSearchParams(searchParams.toString());
      if (page > 1) next.set("page", String(page));
      else next.delete("page");
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [searchParams, router, pathname],
  );

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="QA Checklist"
        description="Generated test plans for the modules of an indexed repository."
        action={
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" />
            Create module
          </Button>
        }
      />

      <ListToolbar
        initialSearch={searchParams.get("search") ?? ""}
        placeholder="Search modules and paths"
        onSearchChange={handleSearch}
        filters={
          <ModuleFilters
            projectId={params.projectId}
            onProjectChange={handleProjectChange}
          />
        }
      />

      <Card className="p-0">
        {!isPending && modules.length === 0 ? (
          <EmptyState
            icon={Plus}
            title="No modules yet"
            description="Point a module at a path in an indexed repository, then generate its checklist."
            action={<Button onClick={() => setCreating(true)}>Create module</Button>}
          />
        ) : (
          <>
            <ModuleTable modules={modules} isLoading={isPending} />
            <PaginationFooter
              page={data?.page ?? 1}
              totalPages={data?.totalPages ?? 1}
              totalCount={data?.totalCount ?? 0}
              onPageChange={handlePageChange}
            />
          </>
        )}
      </Card>

      <CreateModuleDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

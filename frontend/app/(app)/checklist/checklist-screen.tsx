"use client";

import { ClipboardCheck, Plus } from "lucide-react";
import { useState } from "react";

import { CreateModuleDialog } from "@/components/checklist/create-module-dialog";
import { ModuleFilters } from "@/components/checklist/module-filters";
import { ModuleTable } from "@/components/checklist/module-table";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { ListToolbar } from "@/components/layout/list-toolbar";
import { PageHeader } from "@/components/layout/page-header";
import { PaginationFooter } from "@/components/layout/pagination-footer";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useChecklistModules } from "@/hooks/use-checklist";
import { useListParams } from "@/hooks/use-list-params";
import type { ChecklistModuleListParams } from "@/lib/api/types";

const EXTRA_PARAMS = ["projectId"] as const;

export function ChecklistScreen() {
  const [creating, setCreating] = useState(false);
  const { params, searchInput, setSearch, setPage, setParam } = useListParams(
    { limit: 25 },
    { extraParams: EXTRA_PARAMS },
  );
  const listParams = params as ChecklistModuleListParams;
  const query = useChecklistModules(listParams);
  const modules = query.data?.items ?? [];

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
        initialSearch={searchInput}
        placeholder="Search modules and paths"
        onSearchChange={setSearch}
        filters={
          <ModuleFilters
            projectId={listParams.projectId}
            onProjectChange={(projectId) => setParam("projectId", projectId)}
          />
        }
      />

      <Card className="p-0">
        {query.isError ? (
          <div className="p-6">
            <ListError error={query.error} onRetry={() => query.refetch()} />
          </div>
        ) : !query.isLoading && modules.length === 0 ? (
          <EmptyState
            icon={ClipboardCheck}
            title={listParams.search ? "No modules match" : "No modules yet"}
            description={
              listParams.search
                ? "Try a different name or path."
                : "Point a module at a path in an indexed repository, then generate its checklist."
            }
            action={<Button onClick={() => setCreating(true)}>Create module</Button>}
          />
        ) : (
          <>
            <ModuleTable modules={modules} isLoading={query.isLoading} />
            <PaginationFooter
              page={query.data?.page ?? 1}
              totalPages={query.data?.totalPages ?? 1}
              totalCount={query.data?.totalCount ?? 0}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>

      <CreateModuleDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

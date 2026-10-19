"use client";

import { ClipboardCheck, Download, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
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
  const t = useTranslations("checklist.screen");
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
        title={t("title")}
        description={t("description")}
        action={
          <div className="flex gap-2">
            {/* Starts the export on whichever project the list is filtered to. */}
            <Button
              variant="outline"
              nativeButton={false}
              render={
                <Link
                  href={
                    listParams.projectId
                      ? `/checklist/export?projectId=${listParams.projectId}`
                      : "/checklist/export"
                  }
                />
              }
            >
              <Download className="size-4" />
              {t("export")}
            </Button>
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-4" />
              {t("createModule")}
            </Button>
          </div>
        }
      />

      <ListToolbar
        initialSearch={searchInput}
        placeholder={t("searchPlaceholder")}
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
            title={listParams.search ? t("noMatchTitle") : t("emptyTitle")}
            description={
              listParams.search ? t("noMatchDescription") : t("emptyDescription")
            }
            action={
              <Button onClick={() => setCreating(true)}>{t("createModule")}</Button>
            }
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

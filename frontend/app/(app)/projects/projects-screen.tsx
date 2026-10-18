"use client";

import { FolderGit2, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { ListToolbar } from "@/components/layout/list-toolbar";
import { PageHeader } from "@/components/layout/page-header";
import { PaginationFooter } from "@/components/layout/pagination-footer";
import { CreateProjectDialog } from "@/components/projects/create-project-dialog";
import { ProjectRowActions } from "@/components/projects/project-row-actions";
import { ProjectTable } from "@/components/projects/project-table";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useListParams } from "@/hooks/use-list-params";
import { useProjects } from "@/hooks/use-projects";
import { SORT } from "@/lib/api/endpoints";

export function ProjectsScreen() {
  const t = useTranslations();
  const [creating, setCreating] = useState(false);
  const { params, searchInput, setSearch, setPage } = useListParams({
    limit: 25,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
  });
  const query = useProjects(params);
  const projects = query.data?.items ?? [];

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title={t("projects.list.title")}
        description={t("projects.list.description")}
        action={
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" />
            {t("projects.list.addProject")}
          </Button>
        }
      />

      <ListToolbar
        initialSearch={searchInput}
        placeholder={t("projects.list.searchPlaceholder")}
        onSearchChange={setSearch}
      />

      <Card className="p-0">
        {query.isError ? (
          <div className="p-6">
            <ListError error={query.error} onRetry={() => query.refetch()} />
          </div>
        ) : !query.isLoading && projects.length === 0 ? (
          <EmptyState
            icon={FolderGit2}
            title={
              params.search
                ? t("projects.list.emptyNoMatch")
                : t("projects.list.emptyNone")
            }
            description={t("projects.list.emptyDescription", {
              appName: t("common.appName"),
            })}
            action={
              <Button onClick={() => setCreating(true)}>
                {t("projects.list.addProject")}
              </Button>
            }
          />
        ) : (
          <>
            <ProjectTable
              projects={projects}
              isLoading={query.isLoading}
              rowActions={(project) => <ProjectRowActions project={project} />}
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

      <CreateProjectDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

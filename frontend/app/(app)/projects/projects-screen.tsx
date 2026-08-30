"use client";

import { FolderGit2, Plus } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
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
        title="Projects"
        description="Every repository indexed on this instance. Anyone here can query any of them."
        action={
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" />
            Add project
          </Button>
        }
      />

      <ListToolbar
        initialSearch={searchInput}
        placeholder="Search projects"
        onSearchChange={setSearch}
      />

      <Card className="p-0">
        {!query.isLoading && projects.length === 0 ? (
          <EmptyState
            icon={FolderGit2}
            title={params.search ? "No projects match" : "No projects yet"}
            description="Add a repository and AskRepo will clone and index it. That takes a few minutes."
            action={<Button onClick={() => setCreating(true)}>Add project</Button>}
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

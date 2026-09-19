"use client";

import { MessagesSquare, UserPlus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { DetailError } from "@/components/feedback/detail-error";
import { JobFailureAlert } from "@/components/feedback/job-failure-alert";
import { NotFound } from "@/components/feedback/not-found";
import { ProjectStatusBadge } from "@/components/feedback/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { AddMemberDialog } from "@/components/projects/add-member-dialog";
import { MemberTable } from "@/components/projects/member-table";
import { ProjectRowActions } from "@/components/projects/project-row-actions";
import { ProjectStats } from "@/components/projects/project-stats";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useProject } from "@/hooks/use-projects";
import { can, PERMISSION } from "@/lib/can";
import { statusLabel } from "@/lib/status";

export function ProjectDetailScreen({ id }: { id: string }) {
  const query = useProject(id);
  const [addingMember, setAddingMember] = useState(false);

  if (query.isLoading) {
    return (
      <div className="mx-auto w-full max-w-7xl space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (query.error) {
    // A project you may not delete answers 403; one that does not exist answers 404.
    // Existence is deliberately public here (response-api.md), so 404 is the only miss.
    return (
      <DetailError
        error={query.error}
        notFoundMessage="That project does not exist, or it has been deleted."
        onRetry={() => query.refetch()}
      />
    );
  }

  const project = query.data;
  if (!project) return <NotFound />;

  const isWorking = project.status === "cloning" || project.status === "indexing";
  const canReadMembers = can(project, PERMISSION.MEMBERSHIP_READ);
  const canGrantMembers = can(project, PERMISSION.MEMBERSHIP_GRANT);

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6">
      <PageHeader
        title={project.name}
        titleAddon={<ProjectStatusBadge status={project.status} />}
        description={
          <span className="font-mono">
            {project.repoUrl} @{project.branch}
          </span>
        }
        action={
          <div className="flex items-center gap-2">
            {project.status === "ready" ? (
              <Button
                nativeButton={false}
                render={<Link href={`/ask?projectId=${project.id}`} />}
              >
                <MessagesSquare className="size-4" />
                Ask about this project
              </Button>
            ) : null}
            <ProjectRowActions project={project} context="detail" />
          </div>
        }
      />

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          {canReadMembers ? <TabsTrigger value="members">Members</TabsTrigger> : null}
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          {isWorking ? (
            <div className="space-y-2">
              <p className="text-muted-foreground text-sm font-medium">
                {statusLabel(project.status)}…
              </p>
              {/*
                Indeterminate on purpose: the API reports a phase, never a percentage.
                Rendering one would mean inventing it, and an invented bar sitting at 60%
                for eight minutes is worse than an honest indeterminate one.
              */}
              <Progress className="h-2" value={null} />
            </div>
          ) : null}

          {project.reindexInProgress ? (
            <Alert variant="info">
              <AlertTitle>Re-index running</AlertTitle>
              <AlertDescription>
                The current index stays queryable until the new one is ready.
              </AlertDescription>
            </Alert>
          ) : null}

          {project.status === "failed" && project.error ? (
            <JobFailureAlert title="Indexing failed" message={project.error} />
          ) : null}

          <ProjectStats project={project} />
        </TabsContent>

        {canReadMembers ? (
          <TabsContent value="members" className="space-y-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold tracking-tight">Members</h2>
                <p className="text-muted-foreground text-sm">
                  Who can reach this project, and as what.
                </p>
              </div>
              {canGrantMembers ? (
                <Button onClick={() => setAddingMember(true)}>
                  <UserPlus className="size-4" />
                  Add member
                </Button>
              ) : null}
            </div>

            <Card className="p-0">
              <MemberTable projectId={project.id} permissions={project.permissions} />
            </Card>

            <AddMemberDialog
              projectId={project.id}
              open={addingMember}
              onOpenChange={setAddingMember}
            />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  );
}

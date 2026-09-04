"use client";

import { MessagesSquare } from "lucide-react";
import Link from "next/link";

import { NotFound } from "@/components/feedback/not-found";
import { ProjectStatusBadge } from "@/components/feedback/status-badge";
import { ProjectRowActions } from "@/components/projects/project-row-actions";
import { ProjectStats } from "@/components/projects/project-stats";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { useProject } from "@/hooks/use-projects";
import { isApiError } from "@/lib/api/errors";
import { statusLabel } from "@/lib/status";

export function ProjectDetailScreen({ id }: { id: string }) {
  const query = useProject(id);

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
    if (isApiError(query.error) && query.error.status === 404) {
      return (
        <NotFound message="That project does not exist, or it has been deleted." />
      );
    }
    return <NotFound message={(query.error as Error).message} />;
  }

  const project = query.data;
  if (!project) return <NotFound />;

  const isWorking = project.status === "cloning" || project.status === "indexing";

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-semibold tracking-tight">{project.name}</h1>
            <ProjectStatusBadge status={project.status} />
          </div>
          <p className="text-muted-foreground mt-1 font-mono text-base">
            {project.repoUrl} @{project.branch}
          </p>
        </div>
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
      </div>

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
        <Alert>
          <AlertTitle>Re-index running</AlertTitle>
          <AlertDescription>
            The current index stays queryable until the new one is ready.
          </AlertDescription>
        </Alert>
      ) : null}

      {project.status === "failed" && project.error ? (
        <Alert className="border-danger">
          <AlertTitle className="text-danger">Indexing failed</AlertTitle>
          {/* Already scrubbed by the backend, so no token can be in it (docs/PRD.md §9). */}
          <AlertDescription className="font-mono text-sm">
            {project.error}
          </AlertDescription>
        </Alert>
      ) : null}

      <ProjectStats project={project} />
    </div>
  );
}

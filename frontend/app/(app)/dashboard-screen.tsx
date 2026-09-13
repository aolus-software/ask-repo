"use client";

import { FolderGit2, MessagesSquare, Plus } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { ProjectStatusBadge } from "@/components/feedback/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useConversations } from "@/hooks/use-conversations";
import { useProjects } from "@/hooks/use-projects";
import { useSession } from "@/hooks/use-session";
import { SORT } from "@/lib/api/endpoints";
import { formatAbsolute, formatRelative } from "@/lib/dates";

export function DashboardScreen() {
  const user = useSession();

  // Five each. The stat tiles read `totalCount` off THESE queries — it comes back on
  // every page of a PaginatedResponse, so a separate limit=1 count would be two extra
  // round trips for a number already in hand.
  const projects = useProjects({
    limit: 5,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
  });
  const conversations = useConversations({
    limit: 5,
    sort: SORT.conversations.updatedAt,
    sortDirection: "desc",
  });

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6">
      <PageHeader
        title={`Welcome back, ${user.name}`}
        description="Ask questions about any codebase indexed on this instance."
      />

      {/*
        No per-status breakdown: GET /projects has no status filter and no aggregate
        route, so "3 indexing · 12 ready" could only be computed from one page and
        would be quietly wrong past 25 projects (design spec §2.6).
      */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card>
          <CardContent className="p-6">
            <p className="text-muted-foreground text-sm font-medium">
              Projects on this instance
            </p>
            {projects.isLoading ? (
              <Skeleton className="mt-1 h-9 w-16" />
            ) : (
              <p className="mt-1 text-3xl font-semibold">
                {projects.data?.totalCount ?? 0}
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <p className="text-muted-foreground text-sm font-medium">
              Your conversations
            </p>
            {conversations.isLoading ? (
              <Skeleton className="mt-1 h-9 w-16" />
            ) : (
              <p className="mt-1 text-3xl font-semibold">
                {conversations.data?.totalCount ?? 0}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-xl font-semibold">Recent projects</CardTitle>
            <Button
              variant="ghost"
              size="sm"
              nativeButton={false}
              render={<Link href="/projects" />}
            >
              View all
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            {projects.isError ? (
              <ListError error={projects.error} onRetry={() => projects.refetch()} />
            ) : projects.isLoading ? (
              Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))
            ) : (projects.data?.items.length ?? 0) === 0 ? (
              <EmptyState
                icon={FolderGit2}
                title="No projects yet"
                description="Add a repository and AskRepo will clone and index it."
                action={
                  <Button nativeButton={false} render={<Link href="/projects" />}>
                    <Plus className="size-4" />
                    Add one
                  </Button>
                }
              />
            ) : (
              projects.data?.items.map((project) => (
                <Link
                  key={project.id}
                  href={`/projects/${project.id}`}
                  className="hover:bg-accent flex items-center justify-between rounded-lg p-2"
                >
                  <span className="truncate font-medium">{project.name}</span>
                  <ProjectStatusBadge status={project.status} />
                </Link>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-xl font-semibold">
              Your recent questions
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              nativeButton={false}
              render={<Link href="/ask" />}
            >
              Ask
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            {conversations.isError ? (
              <ListError
                error={conversations.error}
                onRetry={() => conversations.refetch()}
              />
            ) : conversations.isLoading ? (
              Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))
            ) : (conversations.data?.items.length ?? 0) === 0 ? (
              <EmptyState
                icon={MessagesSquare}
                title="Nothing asked yet"
                description="Ask a question about any indexed project."
                action={
                  <Button nativeButton={false} render={<Link href="/ask" />}>
                    Ask a question
                  </Button>
                }
              />
            ) : (
              conversations.data?.items.map((conversation) => (
                <Link
                  key={conversation.id}
                  href={`/ask/${conversation.id}`}
                  className="hover:bg-accent block rounded-lg p-2"
                >
                  <span className="block truncate font-medium">
                    {conversation.title ?? "Untitled conversation"}
                  </span>
                  <span
                    className="text-muted-foreground block text-xs"
                    title={formatAbsolute(conversation.updatedAt)}
                  >
                    {formatRelative(conversation.updatedAt)}
                  </span>
                </Link>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

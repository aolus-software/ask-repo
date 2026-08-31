"use client";

import { FolderGit2, MessagesSquare, Plus } from "lucide-react";
import Link from "next/link";

import { ProjectStatusBadge } from "@/components/feedback/status-badge";
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
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">
          Welcome back, {user.name}
        </h1>
        <p className="text-muted-foreground mt-1 text-base">
          Ask questions about any codebase indexed on this instance.
        </p>
      </div>

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
            <p className="mt-1 text-3xl font-semibold">
              {projects.isLoading ? "—" : (projects.data?.totalCount ?? 0)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <p className="text-muted-foreground text-sm font-medium">
              Your conversations
            </p>
            <p className="mt-1 text-3xl font-semibold">
              {conversations.isLoading ? "—" : (conversations.data?.totalCount ?? 0)}
            </p>
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
            {projects.isLoading ? (
              Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))
            ) : (projects.data?.items.length ?? 0) === 0 ? (
              <div className="py-6 text-center">
                <FolderGit2 className="text-muted-foreground mx-auto size-8" />
                <p className="text-muted-foreground mt-2 text-base">No projects yet.</p>
                <Button
                  className="mt-3"
                  nativeButton={false}
                  render={<Link href="/projects" />}
                >
                  <Plus className="size-4" />
                  Add one
                </Button>
              </div>
            ) : (
              projects.data?.items.map((project) => (
                <Link
                  key={project.id}
                  href={`/projects/${project.id}`}
                  className="hover:bg-accent flex items-center justify-between rounded-md p-2"
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
            {conversations.isLoading ? (
              Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))
            ) : (conversations.data?.items.length ?? 0) === 0 ? (
              <div className="py-6 text-center">
                <MessagesSquare className="text-muted-foreground mx-auto size-8" />
                <p className="text-muted-foreground mt-2 text-base">
                  Nothing asked yet.
                </p>
                <Button
                  className="mt-3"
                  nativeButton={false}
                  render={<Link href="/ask" />}
                >
                  Ask a question
                </Button>
              </div>
            ) : (
              conversations.data?.items.map((conversation) => (
                <Link
                  key={conversation.id}
                  href={`/ask/${conversation.id}`}
                  className="hover:bg-accent block rounded-md p-2"
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

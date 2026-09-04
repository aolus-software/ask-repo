"use client";

import {
  ExternalLink,
  Eye,
  MessagesSquare,
  MoreHorizontal,
  RefreshCw,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useDeleteProject, useReindexProject } from "@/hooks/use-project-mutations";
import { useSession } from "@/hooks/use-session";
import { isApiError } from "@/lib/api/errors";
import type { ProjectResponse } from "@/lib/api/types";
import { canManageProject } from "@/lib/can";

/**
 * The actions menu for a project, in a list row or on the project's own page.
 *
 * `context` changes only the first entry. On the detail page "View detail" would link
 * to the page the user is already reading, so it becomes the one destination the page
 * cannot reach on its own -- the repository itself.
 */
export function ProjectRowActions({
  project,
  context = "list",
}: {
  project: ProjectResponse;
  context?: "list" | "detail";
}) {
  const user = useSession();
  const [confirmingReindex, setConfirmingReindex] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const reindex = useReindexProject(project.id);
  const remove = useDeleteProject(project.id);
  const canManage = canManageProject(user, project);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Actions for ${project.name}`}
            />
          }
        >
          <MoreHorizontal className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {context === "detail" ? (
            // `noreferrer` alongside `noopener`: the repository host has no business
            // learning which internal instance linked to it.
            <DropdownMenuItem
              render={
                <a href={project.repoUrl} target="_blank" rel="noopener noreferrer" />
              }
            >
              <ExternalLink className="size-4" />
              Open repository
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem render={<Link href={`/projects/${project.id}`} />}>
              <Eye className="size-4" />
              View detail
            </DropdownMenuItem>
          )}
          {project.status === "ready" ? (
            <DropdownMenuItem render={<Link href={`/ask?projectId=${project.id}`} />}>
              <MessagesSquare className="size-4" />
              Ask about this
            </DropdownMenuItem>
          ) : null}

          {/* Shown only to the creator or an admin. The backend still enforces it. */}
          {canManage ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setConfirmingReindex(true)}>
                <RefreshCw className="size-4" />
                Re-index
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setConfirmingDelete(true)}>
                <Trash2 className="size-4" />
                Delete
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      <ConfirmDialog
        open={confirmingReindex}
        onOpenChange={setConfirmingReindex}
        title={`Re-index ${project.name}?`}
        description="The project stays queryable throughout. New vectors are written alongside the current index and swapped in only when the run succeeds."
        confirmLabel="Re-index"
        isPending={reindex.isPending}
        error={reindex.error}
        onConfirm={() =>
          reindex.mutate(undefined, {
            onSuccess: (result) => {
              // The 202 carries an outcome flag precisely so a no-op is not reported
              // as an action (docs/PRD.md §5.1). Toasting success for both would
              // waste the flag at the last step.
              toast.success(
                result.enqueued ? "Re-index started" : "A re-index is already running",
              );
              setConfirmingReindex(false);
            },
          })
        }
      />

      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title={`Delete ${project.name}?`}
        description="Its index is destroyed and every conversation against it is removed, for everyone. Re-creating it means a full re-clone and re-embed."
        confirmLabel="Delete project"
        isPending={remove.isPending}
        error={remove.error}
        onConfirm={() =>
          remove.mutate(undefined, {
            onSuccess: () => {
              toast.success(`${project.name} deleted`);
              setConfirmingDelete(false);
            },
            onError: (error) => {
              // The one designed-for failure: DELETE must reach Qdrant to satisfy the
              // same-operation hard delete (docs/PRD.md §5.1), and commits nothing if
              // it cannot. Without this message it looks like a silent no-op.
              if (isApiError(error) && error.code === "VECTOR_STORE_UNAVAILABLE") {
                toast.error(
                  "The vector store is unreachable, so nothing was deleted.",
                  {
                    description: "The project is unchanged. Try again once it is back.",
                  },
                );
                setConfirmingDelete(false);
              }
            },
          })
        }
      />
    </>
  );
}

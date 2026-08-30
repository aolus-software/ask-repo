"use client";

import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useReindexProject } from "@/hooks/use-project-mutations";
import { useProject } from "@/hooks/use-projects";
import { useSession } from "@/hooks/use-session";
import { isApiError } from "@/lib/api/errors";
import { canManageProject } from "@/lib/can";

/**
 * Pre-flight failures arrive as ordinary HTTP errors before any body, so they render
 * in the conversation where the question was asked, not as a toast — they are about
 * this turn (design spec §9.8).
 *
 * Still mounted only when there IS an error, but the project query it needs for the
 * re-index button is no longer the reason: the screen now shows the project in its
 * header, so `useProject(projectId)` is already in cache by the time this renders and
 * this reads it rather than issuing a request.
 */
export function PreflightError({
  error,
  projectId,
}: {
  error: unknown;
  projectId: string;
}) {
  const user = useSession();
  const project = useProject(projectId);
  const reindex = useReindexProject(projectId);

  if (!isApiError(error)) {
    return (
      <Alert className="border-danger">
        <AlertTitle className="text-danger">
          That question could not be answered
        </AlertTitle>
        <AlertDescription>
          {error instanceof Error ? error.message : "Something went wrong."}
        </AlertDescription>
      </Alert>
    );
  }

  if (error.code === "EMBEDDING_MODEL_CHANGED") {
    const canManage = project.data ? canManageProject(user, project.data) : false;
    return (
      <Alert className="border-danger">
        <AlertTitle className="text-danger">This project needs re-indexing</AlertTitle>
        <AlertDescription className="space-y-3">
          <p>
            It was indexed with a different embedding model, so its stored vectors
            cannot be searched with the one this instance runs now. Re-index it and
            questions will work again.
          </p>
          {canManage ? (
            <Button
              size="sm"
              disabled={reindex.isPending}
              onClick={() =>
                reindex.mutate(undefined, {
                  onSuccess: (result) =>
                    toast.success(
                      result.enqueued
                        ? "Re-index started"
                        : "A re-index is already running",
                    ),
                })
              }
            >
              Re-index now
            </Button>
          ) : (
            <p className="text-sm">
              Ask the person who added it, or an administrator, to re-index.
            </p>
          )}
        </AlertDescription>
      </Alert>
    );
  }

  if (error.code === "PROJECT_NOT_READY") {
    return (
      <Alert>
        <AlertTitle>This project is not ready yet</AlertTitle>
        <AlertDescription>
          It is still cloning or indexing. Questions work once it reaches “Ready”.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <Alert className="border-danger">
      <AlertTitle className="text-danger">
        That question could not be answered
      </AlertTitle>
      <AlertDescription>{error.message}</AlertDescription>
    </Alert>
  );
}

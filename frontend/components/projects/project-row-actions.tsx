"use client";

import {
  ExternalLink,
  Eye,
  FlaskConical,
  MessagesSquare,
  MoreHorizontal,
  RefreshCw,
  Trash2,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
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
import { isApiError } from "@/lib/api/errors";
import type { ProjectResponse } from "@/lib/api/types";
import { PERMISSION, can } from "@/lib/can";

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
  const t = useTranslations("projects.rowActions");
  const [confirmingReindex, setConfirmingReindex] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const reindex = useReindexProject(project.id);
  const remove = useDeleteProject(project.id);
  const canReindex = can(project, PERMISSION.PROJECT_REINDEX);
  const canDelete = can(project, PERMISSION.PROJECT_DELETE);
  const canReadMembers = can(project, PERMISSION.MEMBERSHIP_READ);
  const canReadEval = can(project, PERMISSION.EVAL_READ);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("menuLabel", { name: project.name })}
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
              {t("openRepository")}
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem render={<Link href={`/projects/${project.id}`} />}>
              <Eye className="size-4" />
              {t("viewDetail")}
            </DropdownMenuItem>
          )}
          {project.status === "ready" ? (
            <DropdownMenuItem render={<Link href={`/ask?projectId=${project.id}`} />}>
              <MessagesSquare className="size-4" />
              {t("askAboutThis")}
            </DropdownMenuItem>
          ) : null}
          {/* Shortcuts into the detail page's tabs, which open from the hash. Not on the
              detail page itself, where the tabs are already on screen. */}
          {context === "list" && canReadMembers ? (
            <DropdownMenuItem
              render={<Link href={`/projects/${project.id}#members`} />}
            >
              <Users className="size-4" />
              {t("members")}
            </DropdownMenuItem>
          ) : null}
          {context === "list" && canReadEval ? (
            <DropdownMenuItem render={<Link href={`/projects/${project.id}#eval`} />}>
              <FlaskConical className="size-4" />
              {t("eval")}
            </DropdownMenuItem>
          ) : null}

          {/* Shown only when the user has the specific permission. The backend still enforces it. */}
          {canReindex || canDelete ? <DropdownMenuSeparator /> : null}
          {canReindex ? (
            <DropdownMenuItem onClick={() => setConfirmingReindex(true)}>
              <RefreshCw className="size-4" />
              {t("reindex")}
            </DropdownMenuItem>
          ) : null}
          {canDelete ? (
            <DropdownMenuItem onClick={() => setConfirmingDelete(true)}>
              <Trash2 className="size-4" />
              {t("delete")}
            </DropdownMenuItem>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      <ConfirmDialog
        open={confirmingReindex}
        onOpenChange={setConfirmingReindex}
        title={t("reindexDialog.title", { name: project.name })}
        description={t("reindexDialog.description")}
        confirmLabel={t("reindexDialog.confirm")}
        isPending={reindex.isPending}
        error={reindex.error}
        onConfirm={() =>
          reindex.mutate(undefined, {
            onSuccess: (result) => {
              // The 202 carries an outcome flag precisely so a no-op is not reported
              // as an action (docs/PRD.md §5.1). Toasting success for both would
              // waste the flag at the last step.
              toast.success(
                result.enqueued
                  ? t("reindexDialog.started")
                  : t("reindexDialog.alreadyRunning"),
              );
              setConfirmingReindex(false);
            },
          })
        }
      />

      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title={t("deleteDialog.title", { name: project.name })}
        description={t("deleteDialog.description")}
        confirmLabel={t("deleteDialog.confirm")}
        isPending={remove.isPending}
        error={remove.error}
        onConfirm={() =>
          remove.mutate(undefined, {
            onSuccess: () => {
              toast.success(t("deleteDialog.deleted"));
              setConfirmingDelete(false);
            },
            onError: (error) => {
              // The one designed-for failure: DELETE must reach Qdrant to satisfy the
              // same-operation hard delete (docs/PRD.md §5.1), and commits nothing if
              // it cannot. Without this message it looks like a silent no-op.
              if (isApiError(error) && error.code === "VECTOR_STORE_UNAVAILABLE") {
                toast.error(t("deleteDialog.vectorStoreDown"), {
                  description: t("deleteDialog.vectorStoreDownDetail"),
                });
                setConfirmingDelete(false);
              }
            },
          })
        }
      />
    </>
  );
}

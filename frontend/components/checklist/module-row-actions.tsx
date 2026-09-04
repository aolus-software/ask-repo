"use client";

import { Edit2, Eye, MoreHorizontal, Play, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { FormDialog } from "@/components/form/form-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  useDeleteChecklistModule,
  useGenerateChecklistModule,
  useUpdateChecklistModule,
} from "@/hooks/use-checklist-mutations";
import { useSession } from "@/hooks/use-session";
import { fieldError } from "@/lib/api/errors";
import type { ChecklistModuleResponse } from "@/lib/api/types";
import { canManageProject } from "@/lib/can";

export function ModuleRowActions({ module }: { module: ChecklistModuleResponse }) {
  const user = useSession();
  const [editingName, setEditingName] = useState(module.name);
  const [editingPath, setEditingPath] = useState(module.sourcePath);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [editingDialog, setEditingDialog] = useState(false);

  const generate = useGenerateChecklistModule(module.id);
  const update = useUpdateChecklistModule(module.id);
  const remove = useDeleteChecklistModule(module.id);
  const canManage = canManageProject(user, module);

  const isGenerating = module.status === "generating" || !!module.pendingChangeSetId;
  const generateDisabledReason =
    module.status === "generating"
      ? "Generation is already in progress"
      : module.pendingChangeSetId
        ? "Review pending changes before generating again"
        : undefined;

  function handleEditSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const changes: { name?: string; sourcePath?: string } = {};
    if (editingName !== module.name) changes.name = editingName;
    if (editingPath !== module.sourcePath) changes.sourcePath = editingPath;

    if (Object.keys(changes).length === 0) {
      setEditingDialog(false);
      return;
    }

    update.mutate(changes, {
      onSuccess: () => {
        toast.success("Module updated");
        setEditingDialog(false);
      },
    });
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Actions for ${module.name}`}
            />
          }
        >
          <MoreHorizontal className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {/*
            A real link, not an onClick router push: the module name in the row is one
            too, and a menu entry that cannot be middle-clicked or opened in a new tab
            behaves differently from the thing beside it for no reason.
          */}
          <DropdownMenuItem render={<Link href={`/checklist/${module.id}`} />}>
            <Eye className="size-4" />
            View detail
          </DropdownMenuItem>
          {isGenerating ? (
            <Tooltip>
              <TooltipTrigger>
                <DropdownMenuItem disabled>
                  <Play className="size-4" />
                  Generate
                </DropdownMenuItem>
              </TooltipTrigger>
              <TooltipContent>{generateDisabledReason}</TooltipContent>
            </Tooltip>
          ) : (
            <DropdownMenuItem onClick={() => generate.mutate()}>
              <Play className="size-4" />
              Generate
            </DropdownMenuItem>
          )}

          {canManage ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setEditingDialog(true)}>
                <Edit2 className="size-4" />
                Edit
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setConfirmingDelete(true)}>
                <Trash2 className="size-4" />
                Delete
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      <FormDialog
        open={editingDialog}
        onOpenChange={setEditingDialog}
        title="Edit module"
        submitLabel="Update"
        isPending={update.isPending}
        error={update.error}
        onSubmit={handleEditSubmit}
      >
        <Field>
          <FieldLabel htmlFor="edit-name">Name</FieldLabel>
          <Input
            id="edit-name"
            value={editingName}
            onChange={(e) => setEditingName(e.target.value)}
            aria-invalid={Boolean(fieldError(update.error, "name"))}
          />
          {fieldError(update.error, "name") ? (
            <FieldError>{fieldError(update.error, "name")}</FieldError>
          ) : null}
        </Field>

        <Field>
          <FieldLabel htmlFor="edit-path">Source path</FieldLabel>
          <Input
            id="edit-path"
            className="font-mono"
            value={editingPath}
            onChange={(e) => setEditingPath(e.target.value)}
            aria-invalid={Boolean(fieldError(update.error, "sourcePath"))}
          />
          <FieldDescription>
            Repository-relative path, e.g. backend/app/auth
          </FieldDescription>
          {fieldError(update.error, "sourcePath") ? (
            <FieldError>{fieldError(update.error, "sourcePath")}</FieldError>
          ) : null}
        </Field>
      </FormDialog>

      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title={`Delete ${module.name}?`}
        description="This deletes the module's test cases, its proposed changes, and its chat. Recorded results go with them."
        confirmLabel="Delete module"
        isPending={remove.isPending}
        error={remove.error}
        onConfirm={() =>
          remove.mutate(undefined, {
            onSuccess: () => {
              toast.success(`${module.name} deleted`);
              setConfirmingDelete(false);
            },
          })
        }
      />
    </>
  );
}

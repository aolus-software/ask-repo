"use client";

import { Edit2, Eye, MoreHorizontal, Play, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { PathPicker } from "@/components/checklist/path-picker";
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
import { useProject } from "@/hooks/use-projects";
import { useErrorText, useFieldErrorText } from "@/lib/i18n/error-text";
import type { ChecklistModuleResponse } from "@/lib/api/types";
import { PERMISSION, can } from "@/lib/can";

export function ModuleRowActions({ module }: { module: ChecklistModuleResponse }) {
  const t = useTranslations("checklist.rowActions");
  const errorText = useErrorText();
  const fieldErrorText = useFieldErrorText();
  const [editingName, setEditingName] = useState(module.name);
  const [editingPath, setEditingPath] = useState(module.sourcePath);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [editingDialog, setEditingDialog] = useState(false);

  const generate = useGenerateChecklistModule(module.id);
  const update = useUpdateChecklistModule(module.id);
  const nameError = fieldErrorText(update.error, "name");
  const sourcePathError = fieldErrorText(update.error, "sourcePath");
  const remove = useDeleteChecklistModule(module.id);
  const project = useProject(module.projectId);
  const canEditModule = project.data
    ? can(project.data, PERMISSION.MODULE_EDIT)
    : false;
  const canDeleteModule = project.data
    ? can(project.data, PERMISSION.MODULE_DELETE)
    : false;

  const canGenerate = project.data ? can(project.data, PERMISSION.GENERATE_RUN) : false;

  // The same three reasons the module's own screen gives, in the same order. The
  // permission is one of them: without it the menu offered an enabled Generate that
  // the backend correctly refused, and the refusal went nowhere
  // (`docs/audit-finding-solved-logs.md` §U6.5).
  const generateDisabledReason =
    module.status === "generating"
      ? t("generationInProgress")
      : module.pendingChangeSetId
        ? t("reviewPendingFirst")
        : !canGenerate
          ? t("noGeneratePermission")
          : undefined;
  const isGenerating = generateDisabledReason !== undefined;

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
        toast.success(t("updated"));
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
              aria-label={t("actionsFor", { name: module.name })}
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
            {t("viewDetail")}
          </DropdownMenuItem>
          {isGenerating ? (
            <Tooltip>
              <TooltipTrigger>
                <DropdownMenuItem disabled>
                  <Play className="size-4" />
                  {t("generate")}
                </DropdownMenuItem>
              </TooltipTrigger>
              <TooltipContent>{generateDisabledReason}</TooltipContent>
            </Tooltip>
          ) : (
            <DropdownMenuItem
              onClick={() =>
                generate.mutate(undefined, {
                  onSuccess: () => toast.success(t("generationStarted")),
                  onError: (error) => toast.error(errorText(error)),
                })
              }
            >
              <Play className="size-4" />
              {t("generate")}
            </DropdownMenuItem>
          )}

          {canEditModule || canDeleteModule ? <DropdownMenuSeparator /> : null}
          {canEditModule ? (
            <DropdownMenuItem
              onClick={() => {
                // Re-seed from the module every time, the way `item-grid`'s
                // `startEditing` does. `useState` seeds once at mount and the row stays
                // mounted as long as the list does, so without this a cancelled edit
                // comes back as the field's value and reads as the saved one
                // (`docs/audit-finding-solved-logs.md` §U5.8).
                setEditingName(module.name);
                setEditingPath(module.sourcePath);
                setEditingDialog(true);
              }}
            >
              <Edit2 className="size-4" />
              {t("edit")}
            </DropdownMenuItem>
          ) : null}
          {canDeleteModule ? (
            <DropdownMenuItem onClick={() => setConfirmingDelete(true)}>
              <Trash2 className="size-4" />
              {t("delete")}
            </DropdownMenuItem>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      <FormDialog
        open={editingDialog}
        onOpenChange={setEditingDialog}
        title={t("editTitle")}
        submitLabel={t("update")}
        isPending={update.isPending}
        error={update.error}
        onSubmit={handleEditSubmit}
      >
        <Field>
          <FieldLabel htmlFor="edit-name">{t("name")}</FieldLabel>
          <Input
            id="edit-name"
            value={editingName}
            onChange={(e) => setEditingName(e.target.value)}
            aria-invalid={Boolean(nameError)}
          />
          {nameError ? <FieldError>{nameError}</FieldError> : null}
        </Field>

        <Field>
          <FieldLabel htmlFor="edit-path">{t("sourcePath")}</FieldLabel>
          <PathPicker
            projectId={module.projectId}
            value={editingPath}
            onValueChange={setEditingPath}
            inputId="edit-path"
            invalid={Boolean(sourcePathError)}
          />
          <FieldDescription>{t("sourcePathHint")}</FieldDescription>
          {sourcePathError ? <FieldError>{sourcePathError}</FieldError> : null}
        </Field>
      </FormDialog>

      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title={t("deleteTitle", { name: module.name })}
        description={t("deleteDescription")}
        confirmLabel={t("deleteConfirm")}
        isPending={remove.isPending}
        error={remove.error}
        onConfirm={() =>
          remove.mutate(undefined, {
            onSuccess: () => {
              toast.success(t("deleted"));
              setConfirmingDelete(false);
            },
          })
        }
      />
    </>
  );
}

"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { PathPicker } from "@/components/checklist/path-picker";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  useCreateChecklistModule,
  useGenerateChecklistModuleById,
} from "@/hooks/use-checklist-mutations";
import { useProjects } from "@/hooks/use-projects";
import { useFieldErrorText } from "@/lib/i18n/error-text";
import { SORT } from "@/lib/api/endpoints";
import type { ProjectResponse } from "@/lib/api/types";
import { PERMISSION, can } from "@/lib/can";

const EMPTY = { projectId: "", name: "", sourcePath: "" };

export function CreateModuleDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("checklist.createModuleDialog");
  const fieldErrorText = useFieldErrorText();
  const [values, setValues] = useState(EMPTY);
  const mutation = useCreateChecklistModule();
  const projectIdError = fieldErrorText(mutation.error, "projectId");
  const nameError = fieldErrorText(mutation.error, "name");
  const sourcePathError = fieldErrorText(mutation.error, "sourcePath");
  const generate = useGenerateChecklistModuleById();

  const query = useProjects({
    limit: 100,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
  });

  // Mirrors the backend gate; it does not replace it. Offering a project the caller
  // cannot create a module in produces a 403 they cannot act on, the same reasoning
  // that already excludes a project that is not indexed yet.
  const readyProjects = (query.data?.items ?? []).filter(
    (p) => p.status === "ready" && can(p, PERMISSION.MODULE_CREATE),
  );
  const selectedProject = readyProjects.find((p) => p.id === values.projectId) ?? null;

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!values.projectId.trim()) {
      return;
    }
    if (!values.name.trim()) {
      return;
    }
    if (!values.sourcePath.trim()) {
      return;
    }

    mutation.mutate(
      {
        projectId: values.projectId,
        name: values.name.trim(),
        sourcePath: values.sourcePath.trim(),
      },
      {
        // Generation is fired here rather than folded into the create request: the
        // module exists either way, and chaining them would report a generation
        // failure as a failed create, inviting a retry that makes a second module.
        onSuccess: (module) => {
          toast.success(t("created"));
          setValues(EMPTY);
          onOpenChange(false);
          generate.mutate(module.id, {
            onError: () => toast.error(t("generationNotStarted")),
          });
        },
      },
    );
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title")}
      description={t("description")}
      submitLabel={t("submit")}
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel>
          {t("project")} <span className="text-danger-text">*</span>
        </FieldLabel>
        <Combobox
          items={readyProjects}
          value={selectedProject}
          onValueChange={(next: ProjectResponse | null) => {
            if (next) setValues({ ...values, projectId: next.id });
          }}
          itemToStringLabel={(project: ProjectResponse) => project.name}
        >
          <ComboboxInput
            className="w-full"
            placeholder={query.isLoading ? t("loadingProjects") : t("searchProjects")}
            aria-label={t("projectAria")}
          />
          <ComboboxContent>
            <ComboboxEmpty>
              {query.isLoading ? t("loading") : t("noProjectMatches")}
            </ComboboxEmpty>
            <ComboboxList>
              {(project: ProjectResponse) => (
                <ComboboxItem key={project.id} value={project}>
                  <span className="truncate">{project.name}</span>
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
        <FieldDescription>{t("projectHint")}</FieldDescription>
        {projectIdError ? <FieldError>{projectIdError}</FieldError> : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="name">
          {t("name")} <span className="text-danger-text">*</span>
        </FieldLabel>
        <Input
          id="name"
          placeholder={t("namePlaceholder")}
          value={values.name}
          onChange={(event) => setValues({ ...values, name: event.target.value })}
          aria-invalid={Boolean(nameError)}
        />
        {nameError ? <FieldError>{nameError}</FieldError> : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="sourcePath">
          {t("sourcePath")} <span className="text-danger-text">*</span>
        </FieldLabel>
        <PathPicker
          projectId={values.projectId}
          value={values.sourcePath}
          onValueChange={(sourcePath) => setValues({ ...values, sourcePath })}
          inputId="sourcePath"
          invalid={Boolean(sourcePathError)}
        />
        <FieldDescription>{t("sourcePathHint")}</FieldDescription>
        {sourcePathError ? <FieldError>{sourcePathError}</FieldError> : null}
      </Field>
    </FormDialog>
  );
}

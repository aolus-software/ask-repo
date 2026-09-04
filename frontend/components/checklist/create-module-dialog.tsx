"use client";

import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
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
import { fieldError } from "@/lib/api/errors";
import { SORT } from "@/lib/api/endpoints";
import type { ProjectResponse } from "@/lib/api/types";

const EMPTY = { projectId: "", name: "", sourcePath: "" };

export function CreateModuleDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [values, setValues] = useState(EMPTY);
  const mutation = useCreateChecklistModule();
  const generate = useGenerateChecklistModuleById();

  const query = useProjects({
    limit: 100,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
  });

  const readyProjects = (query.data?.items ?? []).filter((p) => p.status === "ready");
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
          toast.success("Module created. Generating its checklist\u2026");
          setValues(EMPTY);
          onOpenChange(false);
          generate.mutate(module.id, {
            onError: () =>
              toast.error(
                "Module created, but generation did not start. Use Generate on the module.",
              ),
          });
        },
      },
    );
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Create a module"
      description="Generate a test checklist for a code path in an indexed repository."
      submitLabel="Create module"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel>
          Project <span className="text-danger">*</span>
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
            placeholder={query.isLoading ? "Loading projects…" : "Search projects"}
            aria-label="Project"
          />
          <ComboboxContent>
            <ComboboxEmpty>
              {query.isLoading ? "Loading…" : "No indexed project matches."}
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
        <FieldDescription>
          A module can only be created against an indexed project. Offering others
          produces a 409 the user cannot act on.
        </FieldDescription>
        {fieldError(mutation.error, "projectId") ? (
          <FieldError>{fieldError(mutation.error, "projectId")}</FieldError>
        ) : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="name">
          Name <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="name"
          placeholder="e.g., Auth module"
          value={values.name}
          onChange={(event) => setValues({ ...values, name: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "name"))}
        />
        {fieldError(mutation.error, "name") ? (
          <FieldError>{fieldError(mutation.error, "name")}</FieldError>
        ) : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="sourcePath">
          Source path <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="sourcePath"
          className="font-mono"
          placeholder="backend/app/auth"
          value={values.sourcePath}
          onChange={(event) => setValues({ ...values, sourcePath: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "sourcePath"))}
        />
        <FieldDescription>
          Repository-relative path, e.g. backend/app/auth
        </FieldDescription>
        {fieldError(mutation.error, "sourcePath") ? (
          <FieldError>{fieldError(mutation.error, "sourcePath")}</FieldError>
        ) : null}
      </Field>
    </FormDialog>
  );
}

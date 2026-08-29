"use client";

import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useCreateProject } from "@/hooks/use-project-mutations";
import { fieldError } from "@/lib/api/errors";

const EMPTY = { repoUrl: "", branch: "main", pat: "" };

export function CreateProjectDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [values, setValues] = useState(EMPTY);
  const [urlError, setUrlError] = useState<string | undefined>();
  const mutation = useCreateProject();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    // Required and shape only. The real validation — https, host allowlist, private
    // address rejection at connect time — is a security control on the backend
    // (docs/PRD.md §9) and is not mirrored here.
    if (!values.repoUrl.trim()) {
      setUrlError("Enter a repository URL.");
      return;
    }
    setUrlError(undefined);

    mutation.mutate(
      {
        repoUrl: values.repoUrl.trim(),
        branch: values.branch.trim() || "main",
        pat: values.pat || undefined,
      },
      {
        onSuccess: (project) => {
          // Closes on 201. The clone and index then run for minutes and progress
          // shows on the row — never hold a dialog open on a job (forms.md §10).
          toast.success(`${project.name} queued for indexing`);
          setValues(EMPTY);
          onOpenChange(false);
        },
      },
    );
  }

  const repoUrlError = urlError ?? fieldError(mutation.error, "repoUrl");

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add a project"
      description="AskRepo clones the repository, indexes it, and deletes the working copy."
      submitLabel="Add project"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="repoUrl">
          Repository URL <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="repoUrl"
          className="font-mono"
          placeholder="https://github.com/your-org/your-repo"
          value={values.repoUrl}
          onChange={(event) => setValues({ ...values, repoUrl: event.target.value })}
          aria-invalid={Boolean(repoUrlError)}
        />
        {repoUrlError ? (
          <FieldError>{repoUrlError}</FieldError>
        ) : (
          <FieldDescription>An https URL on an allowed host.</FieldDescription>
        )}
      </Field>

      <Field>
        <FieldLabel htmlFor="branch">Branch</FieldLabel>
        <Input
          id="branch"
          className="font-mono"
          value={values.branch}
          onChange={(event) => setValues({ ...values, branch: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "branch"))}
        />
        {fieldError(mutation.error, "branch") ? (
          <FieldError>{fieldError(mutation.error, "branch")}</FieldError>
        ) : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="pat">Access token</FieldLabel>
        <Input
          id="pat"
          type="password"
          autoComplete="off"
          value={values.pat}
          onChange={(event) => setValues({ ...values, pat: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "pat"))}
        />
        {fieldError(mutation.error, "pat") ? (
          <FieldError>{fieldError(mutation.error, "pat")}</FieldError>
        ) : (
          // Write-only, and never a masked placeholder that looks like a value: the
          // API never returns a PAT, so a placeholder would be a lie an operator
          // submits thinking it is the real one (forms.md §9).
          <FieldDescription>
            Only for a private repository. Leave blank to keep any stored token
            unchanged. Scope it read-only — everyone on this instance can query what it
            indexes.
          </FieldDescription>
        )}
      </Field>
    </FormDialog>
  );
}

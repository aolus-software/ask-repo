"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useCreateRole } from "@/hooks/use-role-mutations";
import { fieldError } from "@/lib/api/errors";

const EMPTY = { name: "", description: "" };

/**
 * Two fields, so a dialog (forms.md §1). Permissions are set separately, on the
 * matrix page — a role with none does nothing, so on success the operator lands
 * there instead of having to find it.
 */
export function CreateRoleDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const [values, setValues] = useState(EMPTY);
  const mutation = useCreateRole();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(
      { name: values.name, description: values.description || undefined },
      {
        onSuccess: (role) => {
          toast.success(`Role "${role.name}" created`);
          setValues(EMPTY);
          onOpenChange(false);
          router.push(`/settings/roles/${role.id}`);
        },
      },
    );
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Create a role"
      description="Give it a name, then choose what it can do on the next page."
      submitLabel="Create role"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="role-name">
          Name <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="role-name"
          value={values.name}
          onChange={(event) => setValues({ ...values, name: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "name"))}
        />
        {fieldError(mutation.error, "name") ? (
          <FieldError>{fieldError(mutation.error, "name")}</FieldError>
        ) : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="role-description">Description</FieldLabel>
        <Input
          id="role-description"
          value={values.description}
          onChange={(event) =>
            setValues({ ...values, description: event.target.value })
          }
          aria-invalid={Boolean(fieldError(mutation.error, "description"))}
        />
        {fieldError(mutation.error, "description") ? (
          <FieldError>{fieldError(mutation.error, "description")}</FieldError>
        ) : null}
      </Field>
    </FormDialog>
  );
}

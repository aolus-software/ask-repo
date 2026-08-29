"use client";

import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useUpdateUser } from "@/hooks/use-user-mutations";
import { fieldError } from "@/lib/api/errors";
import type { UserResponse } from "@/lib/api/types";

export function EditUserDialog({
  user,
  open,
  onOpenChange,
}: {
  user: UserResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  // Seeded during render, keyed on the row's id — never from an effect
  // (`forms.md` §6). Reopening on a different row re-seeds; the operator's own
  // edits survive a refetch.
  const [seededId, setSeededId] = useState<string | null>(null);
  const [values, setValues] = useState({ name: user.name, isAdmin: user.isAdmin });

  if (seededId !== user.id) {
    setSeededId(user.id);
    setValues({ name: user.name, isAdmin: user.isAdmin });
  }

  const mutation = useUpdateUser(user.id);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(values, {
      onSuccess: () => {
        toast.success("Account updated");
        onOpenChange(false);
      },
    });
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={`Edit ${user.name}`}
      submitLabel="Save changes"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="edit-name">Name</FieldLabel>
        <Input
          id="edit-name"
          value={values.name}
          onChange={(event) => setValues({ ...values, name: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "name"))}
        />
        {fieldError(mutation.error, "name") ? (
          <FieldError>{fieldError(mutation.error, "name")}</FieldError>
        ) : null}
      </Field>

      <Field orientation="horizontal">
        <Checkbox
          id="edit-isAdmin"
          checked={values.isAdmin}
          onCheckedChange={(checked) =>
            setValues({ ...values, isAdmin: checked === true })
          }
        />
        <FieldLabel htmlFor="edit-isAdmin">Administrator</FieldLabel>
      </Field>
    </FormDialog>
  );
}

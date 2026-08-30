"use client";

import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { PasswordField } from "@/components/form/password-field";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useCreateUser } from "@/hooks/use-user-mutations";
import { fieldError } from "@/lib/api/errors";

const EMPTY = { name: "", email: "", password: "", isAdmin: false };

export function CreateUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [values, setValues] = useState(EMPTY);
  const mutation = useCreateUser();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(values, {
      onSuccess: () => {
        toast.success(`Account created for ${values.email}`);
        setValues(EMPTY);
        onOpenChange(false);
      },
    });
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add a user"
      description="They will be asked to choose their own password when they first sign in."
      submitLabel="Create account"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="name">
          Name <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="name"
          value={values.name}
          onChange={(event) => setValues({ ...values, name: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "name"))}
        />
        {fieldError(mutation.error, "name") ? (
          <FieldError>{fieldError(mutation.error, "name")}</FieldError>
        ) : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="email">
          Email <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="email"
          type="email"
          value={values.email}
          onChange={(event) => setValues({ ...values, email: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "email"))}
        />
        {fieldError(mutation.error, "email") ? (
          <FieldError>{fieldError(mutation.error, "email")}</FieldError>
        ) : null}
      </Field>

      <PasswordField
        id="password"
        label="Temporary password"
        value={values.password}
        onChange={(password) => setValues({ ...values, password })}
        serverError={fieldError(mutation.error, "password")}
      />

      <Field orientation="horizontal">
        <Checkbox
          id="isAdmin"
          checked={values.isAdmin}
          onCheckedChange={(checked) =>
            setValues({ ...values, isAdmin: checked === true })
          }
        />
        <FieldLabel htmlFor="isAdmin">Administrator</FieldLabel>
      </Field>
    </FormDialog>
  );
}

"use client";

import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useResetPassword } from "@/hooks/use-user-mutations";
import { fieldError } from "@/lib/api/errors";
import type { UserResponse } from "@/lib/api/types";

export function ResetPasswordDialog({
  user,
  open,
  onOpenChange,
}: {
  user: UserResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [newPassword, setNewPassword] = useState("");
  const mutation = useResetPassword(user.id);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(
      { newPassword },
      {
        onSuccess: () => {
          toast.success(`Password reset for ${user.email}`);
          setNewPassword("");
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={`Reset password for ${user.name}`}
      description="Every session for this account will be signed out."
      submitLabel="Reset password"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="reset-password">
          Temporary password <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="reset-password"
          type="password"
          autoComplete="new-password"
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
          aria-invalid={Boolean(fieldError(mutation.error, "newPassword"))}
        />
        {fieldError(mutation.error, "newPassword") ? (
          <FieldError>{fieldError(mutation.error, "newPassword")}</FieldError>
        ) : (
          <FieldDescription>Communicate it to them directly.</FieldDescription>
        )}
      </Field>
    </FormDialog>
  );
}

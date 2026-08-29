"use client";

import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import {
  ChangePasswordFields,
  type ChangePasswordValues,
} from "@/components/users/change-password-fields";
import { useChangePassword } from "@/hooks/use-change-password";

const EMPTY: ChangePasswordValues = { currentPassword: "", newPassword: "" };

export function ChangePasswordDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [values, setValues] = useState<ChangePasswordValues>(EMPTY);
  const mutation = useChangePassword();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(values, {
      onSuccess: () => {
        toast.success("Password changed");
        setValues(EMPTY);
        onOpenChange(false);
      },
    });
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title="Change your password"
      description="Other sessions will be signed out."
      submitLabel="Change password"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <ChangePasswordFields
        values={values}
        onChange={setValues}
        error={mutation.error}
      />
    </FormDialog>
  );
}

"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { PasswordField } from "@/components/form/password-field";
import { useResetPassword } from "@/hooks/use-user-mutations";
import { useFieldErrorText } from "@/lib/i18n/error-text";
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
  const t = useTranslations("settings.users.reset");
  const fieldErrorText = useFieldErrorText();
  const [newPassword, setNewPassword] = useState("");
  const mutation = useResetPassword(user.id);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(
      { newPassword },
      {
        onSuccess: () => {
          toast.success(t("done"));
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
      title={t("title", { name: user.name })}
      description={t("description")}
      submitLabel={t("submit")}
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <PasswordField
        id="reset-password"
        label={t("fields.password")}
        value={newPassword}
        onChange={setNewPassword}
        serverError={fieldErrorText(mutation.error, "newPassword")}
      />
    </FormDialog>
  );
}

"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { PasswordField } from "@/components/form/password-field";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useCreateUser } from "@/hooks/use-user-mutations";
import { useFieldErrorText } from "@/lib/i18n/error-text";

const EMPTY = { name: "", email: "", password: "", isAdmin: false };

export function CreateUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("settings.users.create");
  const fieldErrorText = useFieldErrorText();
  const [values, setValues] = useState(EMPTY);
  const mutation = useCreateUser();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(values, {
      onSuccess: () => {
        toast.success(t("done"));
        setValues(EMPTY);
        onOpenChange(false);
      },
    });
  }

  const emailError = fieldErrorText(mutation.error, "email");
  const nameError = fieldErrorText(mutation.error, "name");
  const passwordError = fieldErrorText(mutation.error, "password");

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
        <FieldLabel htmlFor="name">
          {t("fields.name")} <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="name"
          value={values.name}
          onChange={(event) => setValues({ ...values, name: event.target.value })}
          aria-invalid={Boolean(nameError)}
        />
        {nameError ? <FieldError>{nameError}</FieldError> : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="email">
          {t("fields.email")} <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="email"
          type="email"
          value={values.email}
          onChange={(event) => setValues({ ...values, email: event.target.value })}
          aria-invalid={Boolean(emailError)}
        />
        {emailError ? <FieldError>{emailError}</FieldError> : null}
      </Field>

      <PasswordField
        id="password"
        label={t("fields.password")}
        value={values.password}
        onChange={(password) => setValues({ ...values, password })}
        serverError={passwordError}
      />

      <Field orientation="horizontal">
        <Checkbox
          id="isAdmin"
          checked={values.isAdmin}
          onCheckedChange={(checked) =>
            setValues({ ...values, isAdmin: checked === true })
          }
        />
        <FieldLabel htmlFor="isAdmin">{t("fields.administrator")}</FieldLabel>
      </Field>
    </FormDialog>
  );
}

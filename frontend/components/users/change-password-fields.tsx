"use client";

import { useTranslations } from "next-intl";

import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { PasswordField } from "@/components/form/password-field";
import { PasswordInput } from "@/components/form/password-input";
import { useFieldErrorText } from "@/lib/i18n/error-text";

export interface ChangePasswordValues {
  currentPassword: string;
  newPassword: string;
}

/**
 * Mounted inside FormPage on the forced route and on the profile's Password section.
 * Moving a form between shells is a swap, not a rewrite (`forms.md` §2) — this is the
 * case that rule exists for, and building it twice would be the visible failure.
 */
export function ChangePasswordFields({
  values,
  onChange,
  error,
}: {
  values: ChangePasswordValues;
  onChange: (values: ChangePasswordValues) => void;
  error: unknown;
}) {
  const t = useTranslations("settings.users.changePassword");
  const fieldErrorText = useFieldErrorText();
  const currentPasswordError = fieldErrorText(error, "currentPassword");
  const newPasswordError = fieldErrorText(error, "newPassword");

  return (
    <>
      <Field>
        <FieldLabel htmlFor="currentPassword">
          {t("current")} <span className="text-danger">*</span>
        </FieldLabel>
        <PasswordInput
          id="currentPassword"
          autoComplete="current-password"
          value={values.currentPassword}
          onChange={(event) =>
            onChange({ ...values, currentPassword: event.target.value })
          }
          aria-invalid={Boolean(currentPasswordError)}
        />
        {currentPasswordError ? <FieldError>{currentPasswordError}</FieldError> : null}
      </Field>

      <PasswordField
        id="newPassword"
        label={t("new")}
        value={values.newPassword}
        onChange={(newPassword) => onChange({ ...values, newPassword })}
        serverError={newPasswordError}
      />
    </>
  );
}

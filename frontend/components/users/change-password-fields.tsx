"use client";

import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { PasswordField } from "@/components/form/password-field";
import { PasswordInput } from "@/components/form/password-input";
import { fieldError } from "@/lib/api/errors";

export interface ChangePasswordValues {
  currentPassword: string;
  newPassword: string;
}

/**
 * Mounted inside FormPage on the forced route and inside FormDialog from the account
 * menu. Moving a form between shells is a swap, not a rewrite (`forms.md` §2) — this
 * is the case that rule exists for, and building it twice would be the visible failure.
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
  return (
    <>
      <Field>
        <FieldLabel htmlFor="currentPassword">
          Current password <span className="text-danger">*</span>
        </FieldLabel>
        <PasswordInput
          id="currentPassword"
          autoComplete="current-password"
          value={values.currentPassword}
          onChange={(event) =>
            onChange({ ...values, currentPassword: event.target.value })
          }
          aria-invalid={Boolean(fieldError(error, "currentPassword"))}
        />
        {fieldError(error, "currentPassword") ? (
          <FieldError>{fieldError(error, "currentPassword")}</FieldError>
        ) : null}
      </Field>

      <PasswordField
        id="newPassword"
        label="New password"
        value={values.newPassword}
        onChange={(newPassword) => onChange({ ...values, newPassword })}
        serverError={fieldError(error, "newPassword")}
      />
    </>
  );
}

"use client";

import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
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
        <Input
          id="currentPassword"
          type="password"
          autoComplete="current-password"
          value={values.currentPassword}
          onChange={(event) => onChange({ ...values, currentPassword: event.target.value })}
          aria-invalid={Boolean(fieldError(error, "currentPassword"))}
        />
        {fieldError(error, "currentPassword") ? (
          <FieldError>{fieldError(error, "currentPassword")}</FieldError>
        ) : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="newPassword">
          New password <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="newPassword"
          type="password"
          autoComplete="new-password"
          value={values.newPassword}
          onChange={(event) => onChange({ ...values, newPassword: event.target.value })}
          aria-invalid={Boolean(fieldError(error, "newPassword"))}
        />
        {fieldError(error, "newPassword") ? (
          <FieldError>{fieldError(error, "newPassword")}</FieldError>
        ) : (
          // Deliberately vague: never restate the backend's password policy
          // (forms.md §4). The backend supplies specifics when they are violated.
          <FieldDescription>
            Choose a strong password you do not use anywhere else.
          </FieldDescription>
        )}
      </Field>
    </>
  );
}

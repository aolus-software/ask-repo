"use client";

import { Check, X } from "lucide-react";
import { useState } from "react";

import { PasswordInput } from "@/components/form/password-input";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { usePasswordPolicy } from "@/hooks/use-password-policy";
import { checkPassword, passwordChecksPass } from "@/lib/password-rules";
import { cn } from "@/lib/utils";

/**
 * A new-password field that shows what is expected while you type and settles into a
 * pass/fail state when you leave it.
 *
 * The rules come from `GET /auth/password-policy`, never from a constant here — see
 * `hooks/use-password-policy.ts` for why. Two honesty constraints follow from that:
 *
 *  - Until the policy loads there is nothing truthful to show, so the checklist stays
 *    hidden rather than guessing at a default.
 *  - Passing every local check is not the same as being accepted: the backend also
 *    screens a common-password wordlist the browser never sees. So a satisfied field
 *    reads "looks good so far", and `serverError` always wins when it arrives.
 */
export function PasswordField({
  id,
  label,
  value,
  onChange,
  serverError,
  autoComplete = "new-password",
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  serverError?: string;
  autoComplete?: string;
}) {
  const { data: policy } = usePasswordPolicy();
  const [focused, setFocused] = useState(false);
  const [touched, setTouched] = useState(false);

  const checks = policy ? checkPassword(value, policy) : [];
  const localValid = policy ? passwordChecksPass(value, policy) : false;

  // The server is authoritative; local state only speaks when it has nothing to say.
  // "Settled" means the operator has left the field having typed something, which is
  // the moment a verdict stops being premature.
  const settled = touched && !focused && value.length > 0;
  const showInvalid =
    Boolean(serverError) || (settled && policy !== undefined && !localValid);
  const showValid = !serverError && settled && localValid;

  // The checklist appears while the field is in use, and stays if it left unsatisfied,
  // so the operator can see what is still missing rather than only that it is wrong.
  const showChecks =
    policy !== undefined && (focused || (settled && !localValid)) && value.length > 0;

  return (
    <Field>
      <FieldLabel htmlFor={id}>
        {label} <span className="text-danger">*</span>
      </FieldLabel>

      <PasswordInput
        id={id}
        autoComplete={autoComplete}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false);
          setTouched(true);
        }}
        aria-invalid={showInvalid}
        aria-describedby={showChecks ? `${id}-checks` : undefined}
        className={cn(showValid && "border-success focus-visible:border-success")}
      />

      {showChecks ? (
        <ul id={`${id}-checks`} className="mt-1 space-y-1">
          {checks.map((check) => (
            <li
              key={check.id}
              className={cn(
                "flex items-center gap-1.5 text-xs",
                check.passed ? "text-success" : "text-muted-foreground",
              )}
            >
              {check.passed ? (
                <Check className="size-3.5 shrink-0" />
              ) : (
                <X className="size-3.5 shrink-0" />
              )}
              {check.label}
            </li>
          ))}
        </ul>
      ) : null}

      {serverError ? (
        <FieldError>{serverError}</FieldError>
      ) : showInvalid ? (
        <FieldError>
          {checks.find((check) => !check.passed)?.label ??
            "That password is not accepted."}
        </FieldError>
      ) : showValid ? (
        // Not "valid" — the wordlist check still happens server-side.
        <FieldDescription className="text-success">Looks good so far.</FieldDescription>
      ) : (
        <FieldDescription>
          Choose a strong password you do not use anywhere else.
        </FieldDescription>
      )}
    </Field>
  );
}

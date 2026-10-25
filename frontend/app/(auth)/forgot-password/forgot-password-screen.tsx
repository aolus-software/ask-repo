"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { FormPage } from "@/components/form/form-page";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";

/**
 * Always the same confirmation, on 202 and on 429 alike: the backend answers every
 * address identically so the route cannot say which accounts exist, and a screen that
 * told a 429 apart would give back what the backend was careful not to (spec §6.7).
 * Only 409 differs — it is the same answer for every caller on the instance.
 */
export function ForgotPasswordScreen() {
  const t = useTranslations("auth");
  const [email, setEmail] = useState("");
  const [localError, setLocalError] = useState<string | undefined>();
  const [done, setDone] = useState(false);

  const mutation = useMutation({
    mutationFn: (address: string) =>
      apiFetch<void>(endpoints.auth.passwordResetRequest, {
        method: "POST",
        body: JSON.stringify({ email: address }),
      }),
    onSuccess: () => setDone(true),
    onError: (error) => {
      if (isApiError(error) && error.code === "RATE_LIMITED") setDone(true);
    },
  });

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim()) return setLocalError(t("validation.emailRequired"));
    if (!email.includes("@")) return setLocalError(t("validation.emailShape"));
    setLocalError(undefined);
    mutation.mutate(email.trim().toLowerCase());
  }

  if (done) {
    return (
      <div className="w-full max-w-sm space-y-4 text-center">
        <h1 className="text-xl font-semibold">{t("forgot.doneTitle")}</h1>
        <p className="text-muted-foreground text-sm">{t("forgot.doneBody")}</p>
        <Link
          href="/login"
          className="text-primary text-sm underline-offset-4 hover:underline"
        >
          {t("forgot.backToSignIn")}
        </Link>
      </div>
    );
  }

  const shownError =
    isApiError(mutation.error) && mutation.error.code === "RATE_LIMITED"
      ? null
      : mutation.error;

  return (
    <div className="w-full">
      <FormPage
        width="narrow"
        title={t("forgot.title")}
        description={t("forgot.description")}
        submitLabel={t("forgot.submit")}
        isPending={mutation.isPending}
        error={shownError}
        onSubmit={handleSubmit}
      >
        <Field>
          <FieldLabel htmlFor="email">
            {t("fields.email")} <span className="text-danger-text">*</span>
          </FieldLabel>
          <Input
            id="email"
            name="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={Boolean(localError)}
          />
          {localError ? <FieldError>{localError}</FieldError> : null}
        </Field>
      </FormPage>
      <div className="mt-4 text-center">
        <Link href="/login" className="text-muted-foreground text-sm hover:underline">
          {t("forgot.backToSignIn")}
        </Link>
      </div>
    </div>
  );
}

"use client";

import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { FormError } from "@/components/form/form-error";
import { PasswordInput } from "@/components/form/password-input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ApiError, parseApiError } from "@/lib/api/errors";
import { safeNext } from "@/lib/safe-next";

export function LoginScreen({ resetEnabled }: { resetEnabled: boolean }) {
  const t = useTranslations("auth");
  const tCommon = useTranslations("common");
  const searchParams = useSearchParams();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [localErrors, setLocalErrors] = useState<{ email?: string; password?: string }>(
    {},
  );
  const [error, setError] = useState<unknown>(null);
  const [isPending, setIsPending] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    // Client checks stop at required and shape — never a restatement of a backend
    // rule (forms.md §4). The password policy lives in the backend alone.
    const next: { email?: string; password?: string } = {};
    if (!email.trim()) next.email = t("validation.emailRequired");
    else if (!email.includes("@")) next.email = t("validation.emailShape");
    if (!password) next.password = t("validation.passwordRequired");
    setLocalErrors(next);
    if (Object.keys(next).length > 0) return;

    setIsPending(true);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      });

      if (!response.ok) {
        setError(await parseApiError(response));
        return;
      }

      const { user } = (await response.json()) as {
        user: { mustChangePassword: boolean };
      };
      // A full navigation, not router.push: the shell layout must re-run on the server
      // with the new cookies in place.
      window.location.href = user.mustChangePassword
        ? "/change-password"
        : safeNext(searchParams.get("next"));
    } catch {
      // Status 0 is what `useErrorText` reads as "the server was never reached".
      setError(new ApiError(0, "INTERNAL_ERROR", ""));
    } finally {
      setIsPending(false);
    }
  }

  return (
    <Card className="w-full max-w-sm">
      {/*
        A sibling of CardHeader rather than a child of it: that header is a grid with
        `gap-1`, which is far too tight under a 3rem mark, and a bare `img` as Card's
        own first child would be taken for a cover image and have its top padding
        stripped. Sitting in Card's flex column instead gives the documented card
        spacing for free; the padding is matched to the header's.

        Decorative (`alt=""`) — the title below already reads "Sign in to AskRepo".
      */}
      <div className="px-(--card-spacing)">
        <Image
          src="/logo.png"
          alt=""
          width={48}
          height={48}
          className="size-12"
          priority
        />
      </div>
      <CardHeader>
        <CardTitle className="text-xl font-semibold">
          {t("login.title", { appName: tCommon("appName") })}
        </CardTitle>
        <CardDescription>{t("login.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} noValidate>
          {/*
            The reset flow ends in a full navigation (every session is revoked, so
            there is no client to keep a toast alive across it) — `?reset=1` carries
            the outcome across that navigation instead. Rendered above `FormError`
            since a login attempt on this same load can still fail.
          */}
          {searchParams.get("reset") === "1" ? (
            <Alert variant="info" className="mb-4">
              <AlertDescription>{t("login.resetDone")}</AlertDescription>
            </Alert>
          ) : null}
          {/*
            INVALID_CREDENTIALS renders here, not on a field: the backend returns one
            uniform error for unknown-email and wrong-password, compared against a
            dummy hash so even the timing does not differ (docs/PRD.md §4.0).
            Attaching it to the email field would undo that deliberately.
          */}
          <FormError error={error} />

          <div className="space-y-4">
            <Field>
              <FieldLabel htmlFor="email">
                {t("fields.email")} <span className="text-danger">*</span>
              </FieldLabel>
              <Input
                id="email"
                name="email"
                type="email"
                autoComplete="username"
                placeholder={t("fields.emailPlaceholder")}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                aria-invalid={Boolean(localErrors.email)}
              />
              {localErrors.email ? <FieldError>{localErrors.email}</FieldError> : null}
            </Field>

            <Field>
              <FieldLabel htmlFor="password">
                {t("fields.password")} <span className="text-danger">*</span>
              </FieldLabel>
              <PasswordInput
                id="password"
                name="password"
                autoComplete="current-password"
                placeholder={t("fields.passwordPlaceholder")}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                aria-invalid={Boolean(localErrors.password)}
              />
              {localErrors.password ? (
                <FieldError>{localErrors.password}</FieldError>
              ) : null}
            </Field>
          </div>

          <Button type="submit" className="mt-6 w-full" disabled={isPending}>
            {isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            {t("login.submit")}
          </Button>

          {resetEnabled ? (
            <div className="mt-4 text-center">
              <Link
                href="/forgot-password"
                className="text-muted-foreground text-sm hover:underline"
              >
                {t("login.forgot")}
              </Link>
            </div>
          ) : null}
        </form>
      </CardContent>
    </Card>
  );
}

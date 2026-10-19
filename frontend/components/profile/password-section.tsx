"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { FormPage } from "@/components/form/form-page";
import { Button } from "@/components/ui/button";
import {
  ChangePasswordFields,
  type ChangePasswordValues,
} from "@/components/users/change-password-fields";
import { useChangePassword } from "@/hooks/use-change-password";
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { useErrorText } from "@/lib/i18n/error-text";

const EMPTY: ChangePasswordValues = { currentPassword: "", newPassword: "" };

/**
 * Change password in a page shell — the fields are the ones the forced first-login
 * screen uses (`forms.md` §2: a swap, not a rewrite). The reset link is the Phase 2.4
 * flow, sent to the caller's own address through the same public route the
 * forgot-password page uses; the confirmation is the same neutral sentence on success
 * and on `429 RATE_LIMITED` alike, matching `forgot-password-screen.tsx` — the backend
 * answers every address identically, so this screen must not tell the two apart. Any
 * other failure (a `409` naming why reset is unavailable, a network error) shows its
 * own message instead.
 */
export function PasswordSection({ resetEnabled }: { resetEnabled: boolean }) {
  const t = useTranslations("profile.password");
  const errorText = useErrorText();
  const user = useSession();
  const [values, setValues] = useState<ChangePasswordValues>(EMPTY);
  const change = useChangePassword();
  const reset = useMutation({
    mutationFn: () =>
      apiFetch<void>(endpoints.auth.passwordResetRequest, {
        method: "POST",
        body: JSON.stringify({ email: user.email }),
      }),
    onSuccess: () => toast.success(t("resetSent")),
    onError: (error) => {
      if (isApiError(error) && error.code === "RATE_LIMITED") {
        toast.success(t("resetSent"));
        return;
      }
      toast.error(isApiError(error) ? errorText(error) : t("resetFailed"));
    },
  });

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    change.mutate(values, {
      onSuccess: () => {
        toast.success(t("changed"), {
          description: t("changedDescription"),
        });
        setValues(EMPTY);
      },
    });
  }

  return (
    <div className="space-y-4">
      <FormPage
        title={t("formTitle")}
        description={t("formDescription")}
        submitLabel={t("submit")}
        isPending={change.isPending}
        error={change.error}
        onSubmit={handleSubmit}
      >
        <ChangePasswordFields
          values={values}
          onChange={setValues}
          error={change.error}
        />
      </FormPage>
      {resetEnabled ? (
        <div className="flex items-center justify-between gap-4">
          <p className="text-muted-foreground text-sm">{t("forgotten")}</p>
          <Button
            variant="outline"
            disabled={reset.isPending}
            onClick={() => reset.mutate()}
          >
            {t("emailReset")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

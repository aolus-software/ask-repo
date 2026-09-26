"use client";

import { useMutation } from "@tanstack/react-query";
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

const EMPTY: ChangePasswordValues = { currentPassword: "", newPassword: "" };

/**
 * Change password in a page shell — the fields are the ones the forced first-login
 * screen uses (`forms.md` §2: a swap, not a rewrite). The reset link is the Phase 2.4
 * flow, sent to the caller's own address through the same public route the
 * forgot-password page uses; the confirmation is the same neutral sentence.
 */
export function PasswordSection({ resetEnabled }: { resetEnabled: boolean }) {
  const user = useSession();
  const [values, setValues] = useState<ChangePasswordValues>(EMPTY);
  const change = useChangePassword();
  const reset = useMutation({
    mutationFn: () =>
      apiFetch<void>(endpoints.auth.passwordResetRequest, {
        method: "POST",
        body: JSON.stringify({ email: user.email }),
      }),
    onSettled: () =>
      toast.success("If mail can reach you, a reset link is on its way."),
  });

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    change.mutate(values, {
      onSuccess: () => {
        toast.success("Password changed. Your other sessions were signed out.");
        setValues(EMPTY);
      },
    });
  }

  return (
    <div className="space-y-4">
      <FormPage
        title="Change password"
        description="Your other sessions will be signed out. This one stays signed in."
        submitLabel="Change password"
        isPending={change.isPending}
        error={change.error}
        onSubmit={handleSubmit}
      >
        <ChangePasswordFields values={values} onChange={setValues} error={change.error} />
      </FormPage>
      {resetEnabled ? (
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-4">
          <p className="text-muted-foreground text-sm">
            Forgotten your current password? We can email you a link instead.
          </p>
          <Button
            variant="outline"
            disabled={reset.isPending}
            onClick={() => reset.mutate()}
          >
            Email me a reset link
          </Button>
        </div>
      ) : null}
    </div>
  );
}

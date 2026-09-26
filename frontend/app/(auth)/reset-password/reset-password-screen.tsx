"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";
import { toast } from "sonner";

import { FormPage } from "@/components/form/form-page";
import { PasswordField } from "@/components/form/password-field";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import { fieldError, isApiError } from "@/lib/api/errors";
import { readResetToken } from "@/lib/reset-token";

/**
 * The fragment is invisible to the server, so reading it during render would mismatch
 * SSR's output — and setting it from an effect is exactly the cascading-render shape
 * `react-hooks/set-state-in-effect` rejects. `useSyncExternalStore`'s server snapshot
 * is the same pattern `conversation-rail.tsx` uses for `window.innerWidth`: it matches
 * the pre-hydration render with `undefined` ("not read yet") and corrects to the real
 * token, or `null` for "no token", on the client's first paint.
 */
function subscribeToToken(): () => void {
  return () => {};
}

function getServerTokenSnapshot(): string | null | undefined {
  return undefined;
}

export function ResetPasswordScreen() {
  const router = useRouter();
  const token = useSyncExternalStore(
    subscribeToToken,
    () => readResetToken(window.location.hash),
    getServerTokenSnapshot,
  );
  const [newPassword, setNewPassword] = useState("");

  const mutation = useMutation({
    mutationFn: (input: { token: string; newPassword: string }) =>
      apiFetch<void>(endpoints.auth.passwordResetConfirm, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      toast.success("Password changed. Sign in with your new password.");
      router.push("/login");
    },
  });

  if (token === undefined) return null;

  const invalid =
    token === null ||
    (isApiError(mutation.error) && mutation.error.code === "PASSWORD_RESET_TOKEN_INVALID");

  if (invalid) {
    return (
      <div className="w-full max-w-sm space-y-4 text-center">
        <h1 className="text-xl font-semibold">This link can&apos;t be used</h1>
        <p className="text-muted-foreground text-sm">
          {token === null
            ? "This link is missing its token. Open the link from your email again."
            : "This reset link is invalid or has expired."}
        </p>
        <Link
          href="/forgot-password"
          className="text-primary text-sm underline-offset-4 hover:underline"
        >
          Request a new link
        </Link>
      </div>
    );
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (token) mutation.mutate({ token, newPassword });
  }

  return (
    <div className="w-full">
      <FormPage
        width="narrow"
        title="Choose a new password"
        description="Every other session on this account will be signed out."
        submitLabel="Set password"
        isPending={mutation.isPending}
        error={mutation.error}
        onSubmit={handleSubmit}
      >
        <PasswordField
          id="newPassword"
          label="New password"
          value={newPassword}
          onChange={setNewPassword}
          serverError={fieldError(mutation.error, "newPassword")}
        />
      </FormPage>
    </div>
  );
}

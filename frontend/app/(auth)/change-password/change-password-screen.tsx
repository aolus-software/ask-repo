"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { FormPage } from "@/components/form/form-page";
import { Button } from "@/components/ui/button";
import {
  ChangePasswordFields,
  type ChangePasswordValues,
} from "@/components/users/change-password-fields";
import { useChangePassword } from "@/hooks/use-change-password";

export function ChangePasswordScreen() {
  const router = useRouter();
  const [values, setValues] = useState<ChangePasswordValues>({
    currentPassword: "",
    newPassword: "",
  });
  const mutation = useChangePassword();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(values, {
      onSuccess: () => {
        toast.success("Password changed");
        // A client navigation is enough here: no cookie changed, and the shell
        // layout re-runs on the server for the new route, so it re-reads /auth/me
        // and sees the cleared flag. Contrast the logout below, which must drop the
        // in-memory cache too.
        router.push("/");
      },
    });
  }

  async function logout() {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ all: false }),
    });
    // A hard load, unlike the push above: it discards the React Query cache along
    // with the session, so nothing of this operator survives into the next one.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- clears the in-memory cache with the session
    window.location.assign("/login");
  }

  return (
    <div className="w-full">
      {/* No backHref — the operator cannot navigate away while the flag is set. But a
          logout link stays, because someone who cannot satisfy the form must still be
          able to leave. */}
      <FormPage
        title="Choose a new password"
        description="Your account was created with a temporary password. Set your own to continue."
        submitLabel="Set password"
        isPending={mutation.isPending}
        error={mutation.error}
        onSubmit={handleSubmit}
      >
        <ChangePasswordFields
          values={values}
          onChange={setValues}
          error={mutation.error}
        />
      </FormPage>

      <div className="mt-4 text-center">
        <Button variant="ghost" size="sm" onClick={() => void logout()}>
          Log out instead
        </Button>
      </div>
    </div>
  );
}

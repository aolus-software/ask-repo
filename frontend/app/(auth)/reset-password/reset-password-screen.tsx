"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

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
  // `useSyncExternalStore` calls this getter on every render to check for
  // tearing, not only once — so it must not re-read `window.location.hash`
  // each time. The effect below strips the fragment as soon as the token has
  // been read, and re-reading afterward would find nothing there. The ref
  // caches the one real read for the life of this component instance: the
  // first post-hydration call computes it, and every call after returns the
  // same cached value regardless of what the address bar holds by then.
  const tokenCache = useRef<string | null | undefined>(undefined);
  const token = useSyncExternalStore(
    subscribeToToken,
    () => {
      if (tokenCache.current === undefined) {
        tokenCache.current = readResetToken(window.location.hash);
      }
      return tokenCache.current;
    },
    getServerTokenSnapshot,
  );
  const [newPassword, setNewPassword] = useState("");

  // Strips the token from the address bar once it has been read into component
  // state, so it does not linger in browser history or get forwarded by a referrer
  // header. Runs once the fragment has actually been read (`token` settles past
  // `undefined`) — never during SSR, where there is no `window` to read from.
  useEffect(() => {
    if (token !== undefined) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [token]);

  const mutation = useMutation({
    mutationFn: (input: { token: string; newPassword: string }) =>
      apiFetch<void>(endpoints.auth.passwordResetConfirm, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: async () => {
      // A full navigation is required either way (the change revoked every
      // session), so a toast raised here would never be seen. `/api/auth/logout`
      // clears any stale cookies this browser happens to be carrying — its
      // outcome is ignored, the local cookie clear it always performs is enough —
      // and `?reset=1` carries the success message across the navigation for the
      // login screen to render.
      try {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ all: false }),
        });
      } catch {
        // Ignored: clearing a session that may not exist is best-effort.
      }
      // A full navigation, not router.push: confirm just revoked every session
      // (including this render's own), so the login screen must reload from the
      // server rather than reuse any client-held state.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login?reset=1";
    },
  });

  if (token === undefined) return null;

  const invalid =
    token === null ||
    (isApiError(mutation.error) &&
      mutation.error.code === "PASSWORD_RESET_TOKEN_INVALID");

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
        description="Every session on this account will be signed out."
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

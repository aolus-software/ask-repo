import { Suspense } from "react";

import { LoginScreen } from "@/app/(auth)/login/login-screen";
import { endpoints } from "@/lib/api/endpoints";
import { serverFetch } from "@/lib/api/server";

/**
 * The availability check runs here, server-side: `serverFetch` calls the API directly
 * and needs no cookie. A failed check hides the link rather than failing the page.
 */
async function resetEnabled(): Promise<boolean> {
  try {
    const { enabled } = await serverFetch<{ enabled: boolean }>(
      endpoints.auth.passwordResetAvailability,
    );
    return enabled;
  } catch {
    return false;
  }
}

/** Suspense is required: the screen reads useSearchParams, and next build fails without it. */
export default async function LoginPage() {
  return (
    <Suspense>
      <LoginScreen resetEnabled={await resetEnabled()} />
    </Suspense>
  );
}

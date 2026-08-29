import { Suspense } from "react";

import { LoginScreen } from "@/app/(auth)/login/login-screen";

/** Suspense is required: the screen reads useSearchParams, and next build fails without it. */
export default function LoginPage() {
  return (
    <Suspense>
      <LoginScreen />
    </Suspense>
  );
}

import { redirect } from "next/navigation";

import { AppShell } from "@/components/layout/app-shell";
import { endpoints } from "@/lib/api/endpoints";
import { serverFetch } from "@/lib/api/server";
import type { UserResponse } from "@/lib/api/types";

/**
 * Resolves the operator before the first byte, which eliminates the permission flash
 * structurally: `navigation.md` §4 requires the sidebar never render a filtered list
 * while the profile is pending, and here there is no pending state to get wrong. Do
 * not add a placeholder skeleton back — there is nothing for it to cover.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  let user: UserResponse;
  try {
    user = await serverFetch<UserResponse>(endpoints.auth.me);
  } catch {
    redirect("/login");
  }

  // Enforced here rather than in `proxy.ts`: `must_change_password` is deliberately
  // not a token claim (docs/PRD.md §4.0), and this layout already has the user.
  if (user.mustChangePassword) redirect("/change-password");

  return <AppShell user={user}>{children}</AppShell>;
}

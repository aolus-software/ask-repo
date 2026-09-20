import { redirect } from "next/navigation";

import { endpoints } from "@/lib/api/endpoints";
import { serverFetch } from "@/lib/api/server";
import type { UserResponse } from "@/lib/api/types";
import { settingsNav } from "@/lib/settings-nav";

/**
 * A group's index route only redirects to its first *reachable* child
 * (navigation.md §3). Notifications is the first child that is not `adminOnly`, so a
 * non-admin must resolve here too — redirecting to the first child outright would
 * send every non-admin operator to `/settings/users`, a page they cannot see, the
 * moment they had any reachable settings screen at all.
 */
export default async function SettingsPage() {
  let user: UserResponse;
  try {
    user = await serverFetch<UserResponse>(endpoints.auth.me);
  } catch {
    redirect("/login");
  }

  const child = settingsNav.find((item) => !item.adminOnly || user.isAdmin);
  redirect(child?.href ?? "/");
}

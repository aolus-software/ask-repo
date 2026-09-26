import { redirect } from "next/navigation";

import { endpoints } from "@/lib/api/endpoints";
import { serverFetch } from "@/lib/api/server";
import type { UserResponse } from "@/lib/api/types";
import { settingsNav } from "@/lib/settings-nav";

/**
 * A group's index route only redirects to its first *reachable* child
 * (navigation.md §3). Every child is admin-only, so a non-admin falls through to `/` —
 * the same outcome as before Notifications briefly lived here.
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

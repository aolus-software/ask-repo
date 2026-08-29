import { redirect } from "next/navigation";

/** A group's index route only redirects to its first reachable child (navigation.md §3). */
export default function SettingsPage() {
  redirect("/settings/users");
}

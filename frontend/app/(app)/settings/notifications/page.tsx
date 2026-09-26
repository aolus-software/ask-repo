import { redirect } from "next/navigation";

/** Preferences moved to the profile; old links and bookmarks land on that section. */
export default function NotificationPreferencesPage() {
  redirect("/profile#notifications");
}

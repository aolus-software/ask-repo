import { ProfileScreen } from "@/components/profile/profile-screen";
import { endpoints } from "@/lib/api/endpoints";
import { serverFetch } from "@/lib/api/server";

/**
 * Server-side, like the login page's check: a failed availability read hides the reset
 * button rather than failing the page.
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

export default async function ProfilePage() {
  return <ProfileScreen resetEnabled={await resetEnabled()} />;
}

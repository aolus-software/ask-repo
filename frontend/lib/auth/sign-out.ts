/**
 * The one sign-out implementation, shared by the account menu and the profile's
 * Sessions section: same POST to `/api/auth/logout`, same hard navigation.
 *
 * A hard reload, not `router.push`, and the lint rule is suppressed deliberately:
 * `router.push` keeps the SPA alive, and with it the React Query cache holding the
 * previous operator's projects and conversations. On a shared machine the next
 * person would see that stale data flash before it refetched. A full load drops it.
 */
export async function signOut(all: boolean): Promise<void> {
  await fetch("/api/auth/logout", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ all }),
  });
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- clears the in-memory cache with the session
  window.location.assign("/login");
}

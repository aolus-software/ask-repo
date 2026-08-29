import { cookies } from "next/headers";

import { parseApiError } from "@/lib/api/errors";
import { ACCESS_COOKIE } from "@/lib/auth/cookies";
import { apiUrl } from "@/lib/auth/session";

/**
 * Server Components only: reads the access cookie and calls the backend directly,
 * so an SSR page never makes an HTTP round trip to itself.
 *
 * It never refreshes and never sets a cookie — middleware guarantees a fresh token
 * before the render begins, and a Server Component cannot persist one anyway
 * (design spec §2.3). A 401 here means the token expired between the two, which the
 * caller handles with redirect("/login").
 */
export async function serverFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const store = await cookies();
  const accessToken = store.get(ACCESS_COOKIE)?.value;

  const response = await fetch(`${apiUrl()}${path}`, {
    ...init,
    headers: {
      ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
      ...(init?.body ? { "content-type": "application/json" } : {}),
      ...init?.headers,
    },
    cache: "no-store",
  });

  if (!response.ok) throw await parseApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

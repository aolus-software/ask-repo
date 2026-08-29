import { endpoints } from "@/lib/api/endpoints";

/** The backend base URL. Server-only — the browser never reaches the API directly. */
export function apiUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}

export interface RefreshResult {
  accessToken: string;
  expiresIn: number;
  /** The rotated `name=value` pair to store back in the session cookie. */
  sessionCookie: string;
}

/**
 * Capture the backend's refresh cookie as a verbatim `name=value` pair.
 *
 * By name-agnostic design: `Settings.refresh_cookie_name` is an operator override
 * (`backend/app/config.py:43`), so parsing by a hard-coded name would break silently
 * the moment REFRESH_COOKIE_NAME is set — a login that appears to succeed and a
 * session that cannot refresh.
 */
export function extractSessionCookie(response: Response): string | null {
  const header = response.headers.get("set-cookie");
  if (!header) return null;
  const pair = header.split(";", 1)[0]?.trim();
  return pair && pair.includes("=") ? pair : null;
}

/**
 * Single-flight guard. Two requests can 401 at the same instant and each would
 * present the same refresh token; the backend treats a second presentation of a
 * consumed token as replay and revokes the whole family (docs/PRD.md §4.0).
 *
 * The guard is PER PROCESS. With more than one frontend replica two refreshes can
 * still reach the backend, and it is the backend's 10-second grace window — not this
 * guard — that saves the session. Do not describe this as complete.
 */
let inFlight: Promise<RefreshResult | null> | null = null;

export function refreshSession(sessionCookie: string): Promise<RefreshResult | null> {
  inFlight ??= performRefresh(sessionCookie).finally(() => {
    inFlight = null;
  });
  return inFlight;
}

async function performRefresh(sessionCookie: string): Promise<RefreshResult | null> {
  let response: Response;
  try {
    response = await fetch(`${apiUrl()}${endpoints.auth.refresh}`, {
      method: "POST",
      headers: { cookie: sessionCookie },
      cache: "no-store",
    });
  } catch {
    return null;
  }

  if (!response.ok) return null;

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return null;
  }

  if (typeof body !== "object" || body === null) return null;

  const { accessToken, expiresIn } = body as { accessToken?: unknown; expiresIn?: unknown };
  if (typeof accessToken !== "string" || typeof expiresIn !== "number") return null;

  return {
    accessToken,
    expiresIn,
    // A rotation that sets no cookie leaves the old pair in place rather than clearing it.
    sessionCookie: extractSessionCookie(response) ?? sessionCookie,
  };
}

/** Test-only: drop the in-flight promise so each test starts clean. */
export function __resetRefreshFlight(): void {
  inFlight = null;
}

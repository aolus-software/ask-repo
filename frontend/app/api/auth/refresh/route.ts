import { NextResponse } from "next/server";

import {
  ACCESS_COOKIE,
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  accessCookieMaxAge,
  cookieOptions,
} from "@/lib/auth/cookies";
import { refreshSession } from "@/lib/auth/session";

/**
 * Rotate the session on demand. In normal operation refresh is triggered by the
 * request proxy in `proxy.ts` (navigations) or by the API proxy at
 * `app/api/[...path]` (fetches); this exists for completeness and for a client
 * that wants to renew explicitly.
 */
export async function POST(request: Request): Promise<Response> {
  const sessionCookie = readCookie(request, SESSION_COOKIE);
  if (!sessionCookie) return unauthenticated();

  const result = await refreshSession(sessionCookie);
  if (!result) return unauthenticated();

  const response = new NextResponse(null, { status: 204 });
  response.cookies.set(
    ACCESS_COOKIE,
    result.accessToken,
    cookieOptions(accessCookieMaxAge(result.expiresIn)),
  );
  response.cookies.set(
    SESSION_COOKIE,
    result.sessionCookie,
    cookieOptions(SESSION_MAX_AGE_SECONDS),
  );
  return response;
}

function unauthenticated(): NextResponse {
  const response = NextResponse.json(
    { detail: { code: "INVALID_TOKEN", message: "Your session has expired." } },
    { status: 401 },
  );
  response.cookies.set(ACCESS_COOKIE, "", cookieOptions(0));
  response.cookies.set(SESSION_COOKIE, "", cookieOptions(0));
  return response;
}

function readCookie(request: Request, name: string): string | undefined {
  const header = request.headers.get("cookie");
  if (!header) return undefined;
  for (const part of header.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return undefined;
}

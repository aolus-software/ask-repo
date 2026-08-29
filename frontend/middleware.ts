import { type NextRequest, NextResponse } from "next/server";

import {
  ACCESS_COOKIE,
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  accessCookieMaxAge,
  cookieOptions,
} from "@/lib/auth/cookies";
import { refreshSession } from "@/lib/auth/session";

/**
 * The coarse gate: is there a session at all?
 *
 * Two checks it deliberately does NOT make:
 *  - `must_change_password`, which is not a token claim (docs/PRD.md §4.0), so
 *    middleware could only learn it with an extra API call on every navigation.
 *    `app/(app)/layout.tsx` handles it, having already fetched the user.
 *  - `is_admin`, because middleware sees a path and not a resource. Route
 *    authorization lives in the page body, and the backend is the authority.
 *
 * This is also the refresh point for navigations: a Server Component cannot set a
 * cookie, so a token refreshed during render could never be persisted (spec §2.3).
 */
export async function middleware(request: NextRequest): Promise<NextResponse> {
  const { pathname } = request.nextUrl;
  const isLoginRoute = pathname === "/login";

  const sessionCookie = request.cookies.get(SESSION_COOKIE)?.value;
  const hasAccess = Boolean(request.cookies.get(ACCESS_COOKIE)?.value);

  if (!sessionCookie) {
    return isLoginRoute ? NextResponse.next() : redirectToLogin(request);
  }

  if (isLoginRoute) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  if (hasAccess) return NextResponse.next();

  const refreshed = await refreshSession(sessionCookie);
  if (!refreshed) {
    const response = redirectToLogin(request);
    response.cookies.set(ACCESS_COOKIE, "", cookieOptions(0));
    response.cookies.set(SESSION_COOKIE, "", cookieOptions(0));
    return response;
  }

  const response = NextResponse.next();
  response.cookies.set(
    ACCESS_COOKIE,
    refreshed.accessToken,
    cookieOptions(accessCookieMaxAge(refreshed.expiresIn)),
  );
  response.cookies.set(SESSION_COOKIE, refreshed.sessionCookie, cookieOptions(SESSION_MAX_AGE_SECONDS));
  return response;
}

function redirectToLogin(request: NextRequest): NextResponse {
  const url = new URL("/login", request.url);
  const target = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  if (target !== "/") url.searchParams.set("next", target);
  return NextResponse.redirect(url);
}

export const config = {
  // /api/* is the proxy's own concern; it refreshes for itself.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.svg$).*)"],
};

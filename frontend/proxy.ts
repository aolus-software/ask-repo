import { type NextRequest, NextResponse } from "next/server";

import {
  ACCESS_COOKIE,
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  accessCookieMaxAge,
  cookieOptions,
} from "@/lib/auth/cookies";
import { forwardedHeaders } from "@/lib/auth/forwarded";
import { refreshSession } from "@/lib/auth/session";

/** Pages a signed-out visitor must reach. Everything else redirects to /login. */
const PUBLIC_ROUTES = new Set(["/login", "/forgot-password", "/reset-password"]);

/**
 * The coarse gate: is there a session at all?
 *
 * Two checks it deliberately does NOT make:
 *  - `must_change_password`, which is not a token claim (docs/PRD.md §4.0), so
 *    the proxy could only learn it with an extra API call on every navigation.
 *    `app/(app)/layout.tsx` handles it, having already fetched the user.
 *  - `is_admin`, because the proxy sees a path and not a resource. Route
 *    authorization lives in the page body, and the backend is the authority.
 *
 * This is also the refresh point for navigations: a Server Component cannot set a
 * cookie, so a token refreshed during render could never be persisted (spec §2.3).
 *
 * Named `proxy` in `proxy.ts` because Next 16 renamed the file convention; this is
 * the same request gate that was `middleware.ts`, with no behavioural change. Next
 * errors out if both files exist, so this is a move rather than an addition.
 */
export async function proxy(request: NextRequest): Promise<NextResponse> {
  const { pathname } = request.nextUrl;
  const isPublicRoute = PUBLIC_ROUTES.has(pathname);

  // /forgot-password and /reset-password must work for a visitor who is not signed
  // in at all, which is the ordinary case, but also for one carrying a stale
  // `askrepo_session` cookie with no access cookie: the refresh below would fail
  // and bounce them to /login, silently dropping the reset link's #token fragment.
  // These two routes therefore bypass the session/refresh logic entirely, whatever
  // cookies are present. /login keeps its own handling below — a signed-in visitor
  // is still sent to /.
  if (pathname === "/forgot-password" || pathname === "/reset-password") {
    return NextResponse.next();
  }

  const sessionCookie = request.cookies.get(SESSION_COOKIE)?.value;
  const hasAccess = Boolean(request.cookies.get(ACCESS_COOKIE)?.value);

  if (!sessionCookie) {
    return isPublicRoute ? NextResponse.next() : redirectToLogin(request);
  }

  if (pathname === "/login") {
    return NextResponse.redirect(new URL("/", request.url));
  }

  if (hasAccess) return NextResponse.next();

  const refreshed = await refreshSession(sessionCookie, forwardedHeaders(request));
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
  response.cookies.set(
    SESSION_COOKIE,
    refreshed.sessionCookie,
    cookieOptions(SESSION_MAX_AGE_SECONDS),
  );
  return response;
}

function redirectToLogin(request: NextRequest): NextResponse {
  const url = new URL("/login", request.url);
  const target = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  if (target !== "/") url.searchParams.set("next", target);
  return NextResponse.redirect(url);
}

export const config = {
  // /api/* is the proxy's own concern; it refreshes for itself. Public static
  // assets (the brand logo, manifest icons, the generated manifest route) must
  // be excluded too: the login screen renders /logo.png while unauthenticated,
  // and gating it here redirected the image to HTML, which is what broke both
  // next/image optimization and the manifest fetch.
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|manifest.webmanifest|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};

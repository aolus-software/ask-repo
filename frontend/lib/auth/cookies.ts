/**
 * The session cookies Next sets on its OWN origin. Nothing else constructs cookie
 * options — a second copy is how `secure` ends up set in one place and not the other.
 *
 * Path is "/" rather than the backend's "/auth" (docs/PRD.md §4.0) because middleware
 * runs at paths like /projects and is only sent cookies whose path matches. httpOnly,
 * SameSite and Secure are all preserved. See the design spec §2.2.
 */

/** Holds the JWT. Its own Max-Age IS the expiry check — the JWT is never parsed. */
export const ACCESS_COOKIE = "askrepo_access";

/** Holds the backend's refresh cookie as a verbatim `name=value` pair (spec §4.2). */
export const SESSION_COOKIE = "askrepo_session";

/** Subtracted from `expiresIn` so the cookie dies before the token does. */
export const ACCESS_SKEW_SECONDS = 30;

export const SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

export interface SessionCookieOptions {
  httpOnly: true;
  sameSite: "lax";
  secure: boolean;
  path: "/";
  maxAge: number;
}

export function cookieOptions(maxAge: number): SessionCookieOptions {
  return {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  };
}

/** Clamped so a short or absent `expiresIn` never yields a negative Max-Age. */
export function accessCookieMaxAge(expiresIn: number): number {
  return Math.max(expiresIn - ACCESS_SKEW_SECONDS, 1);
}

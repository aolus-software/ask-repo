import type { NextResponse } from "next/server";

import {
  LOCALE_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  cookieOptions,
} from "@/lib/auth/cookies";
import { isLanguage } from "@/lib/i18n/languages";

/**
 * Mirror a stored language onto the locale cookie. `null` and anything unshipped
 * leave the cookie as it is: a user with no stored language keeps whatever this
 * browser chose, rather than having it wiped at every login (plan Global Constraints).
 */
export function applyLocale(response: NextResponse, language: unknown): void {
  if (isLanguage(language)) {
    response.cookies.set(
      LOCALE_COOKIE,
      language,
      cookieOptions(SESSION_MAX_AGE_SECONDS),
    );
  }
}

/** Forget this browser's language, so `Accept-Language` decides again. */
export function clearLocale(response: NextResponse): void {
  response.cookies.set(LOCALE_COOKIE, "", cookieOptions(0));
}

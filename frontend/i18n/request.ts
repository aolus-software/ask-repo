import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { LOCALE_COOKIE } from "@/lib/auth/cookies";
import { resolveLocale } from "@/lib/i18n/languages";

/** Resolved once per request: cookie, then Accept-Language, then English. */
export default getRequestConfig(async () => {
  const locale = resolveLocale(
    (await cookies()).get(LOCALE_COOKIE)?.value,
    (await headers()).get("accept-language"),
  );
  return {
    locale,
    messages: (await import(`../messages/${locale}/index`)).default,
  };
});

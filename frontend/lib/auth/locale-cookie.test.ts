import { NextResponse } from "next/server";
import { describe, expect, it } from "vitest";

import { LOCALE_COOKIE } from "@/lib/auth/cookies";
import { applyLocale, clearLocale } from "@/lib/auth/locale-cookie";

describe("applyLocale", () => {
  it("sets an httpOnly, Path=/ cookie for a shipped language", () => {
    const response = NextResponse.json({});
    applyLocale(response, "zh-TW");
    const cookie = response.cookies.get(LOCALE_COOKIE);
    expect(cookie?.value).toBe("zh-TW");
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.path).toBe("/");
  });

  it("leaves the cookie alone for null or an unknown code", () => {
    for (const value of [null, undefined, "fr"]) {
      const response = NextResponse.json({});
      applyLocale(response, value);
      expect(response.cookies.get(LOCALE_COOKIE)).toBeUndefined();
    }
  });
});

describe("clearLocale", () => {
  it("expires the cookie", () => {
    const response = NextResponse.json({});
    clearLocale(response);
    expect(response.cookies.get(LOCALE_COOKIE)?.maxAge).toBe(0);
  });
});

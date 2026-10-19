import { describe, expect, it } from "vitest";

import { LANGUAGES, isLanguage, resolveLocale } from "@/lib/i18n/languages";

describe("resolveLocale", () => {
  it("prefers a valid cookie over the header", () => {
    expect(resolveLocale("ko", "id-ID,id;q=0.9")).toBe("ko");
  });

  it("ignores a cookie that is not a shipped language", () => {
    expect(resolveLocale("fr", "ja-JP,ja;q=0.9")).toBe("ja");
  });

  it("walks Accept-Language in q order", () => {
    expect(resolveLocale(undefined, "fr;q=0.9,ms;q=0.8,en;q=0.1")).toBe("ms");
  });

  it("skips a language the client marked not acceptable", () => {
    expect(resolveLocale(undefined, "ja;q=0,id;q=0.5")).toBe("id");
    expect(resolveLocale(undefined, "ja;q=0")).toBe("en");
  });

  it("matches a region to its base language", () => {
    expect(resolveLocale(undefined, "id-ID")).toBe("id");
    expect(resolveLocale(undefined, "en-GB")).toBe("en");
  });

  it("keeps the two Traditional Chinese variants apart", () => {
    expect(resolveLocale(undefined, "zh-HK")).toBe("zh-HK");
    expect(resolveLocale(undefined, "zh-TW")).toBe("zh-TW");
    expect(resolveLocale(undefined, "zh-MO")).toBe("zh-HK");
    expect(resolveLocale(undefined, "zh-Hant")).toBe("zh-TW");
  });

  it("never maps Simplified Chinese to a Traditional catalogue", () => {
    expect(resolveLocale(undefined, "zh-CN,zh;q=0.9")).toBe("en");
  });

  it("falls back to English", () => {
    expect(resolveLocale(undefined, null)).toBe("en");
    expect(resolveLocale(undefined, "")).toBe("en");
  });
});

describe("isLanguage", () => {
  it("accepts exactly the shipped codes", () => {
    for (const code of LANGUAGES) expect(isLanguage(code)).toBe(true);
    expect(isLanguage("zh-hk")).toBe(false);
    expect(isLanguage(null)).toBe(false);
  });
});

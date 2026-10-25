import { describe, expect, it } from "vitest";

import { formatDay, formatRelative } from "@/lib/dates";

const NOW = Date.parse("2026-10-17T12:00:00Z");

describe("formatRelative", () => {
  it("formats in the given locale", () => {
    expect(formatRelative("2026-10-14T12:00:00Z", "en", NOW)).toBe("3 days ago");
    expect(formatRelative("2026-10-14T12:00:00Z", "id", NOW)).toBe("3 hari yang lalu");
    expect(formatRelative("2026-10-14T12:00:00Z", "ja", NOW)).toBe("3 日前");
  });

  it("says now for under a minute, in the locale", () => {
    expect(formatRelative("2026-10-17T11:59:40Z", "en", NOW)).toBe("now");
  });
});

describe("formatDay", () => {
  it("formats a bare day in the locale, date only", () => {
    expect(formatDay("2026-10-24", "en")).toBe("Oct 24, 2026");
    expect(formatDay("2026-10-24", "ja")).not.toBe("2026-10-24");
    expect(formatDay("2026-10-24", "ja")).not.toMatch(/\d:\d/);
  });

  it("never shifts the day with the viewer's time zone", () => {
    expect(formatDay("2026-01-01", "en")).toBe("Jan 1, 2026");
  });

  it("falls back to the ISO day without a locale", () => {
    expect(formatDay("2026-10-24T09:00:00Z")).toBe("2026-10-24");
  });
});

import { describe, expect, it } from "vitest";

import { formatRelative } from "@/lib/dates";

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

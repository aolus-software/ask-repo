import { describe, expect, it } from "vitest";

import { parseDevice } from "@/lib/user-agent";

describe("parseDevice", () => {
  it.each([
    [
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
      ["Chrome", "macOS"],
    ],
    [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 Edg/129.0",
      ["Edge", "Windows"],
    ],
    [
      "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
      ["Firefox", "Linux"],
    ],
    [
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1",
      ["Safari", "iOS"],
    ],
    [
      "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36",
      ["Chrome", "Android"],
    ],
  ])("names %s", (userAgent, [browser, system]) => {
    expect(parseDevice(userAgent)).toEqual({ browser, system });
  });

  it("is null for a missing or blank agent", () => {
    expect(parseDevice(null)).toBeNull();
    expect(parseDevice("   ")).toBeNull();
  });

  it("names neither part when nothing matches", () => {
    expect(parseDevice("curl/8.4.0")).toEqual({ browser: null, system: null });
  });
});

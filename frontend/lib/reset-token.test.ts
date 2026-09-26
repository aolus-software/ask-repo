import { describe, expect, it } from "vitest";

import { readResetToken } from "@/lib/reset-token";

describe("readResetToken", () => {
  it("reads the token from the fragment", () => {
    expect(readResetToken("#token=abc-123_XYZ")).toBe("abc-123_XYZ");
  });

  it("returns null when there is no token", () => {
    expect(readResetToken("")).toBeNull();
    expect(readResetToken("#")).toBeNull();
    expect(readResetToken("#other=1")).toBeNull();
    expect(readResetToken("#token=")).toBeNull();
  });
});

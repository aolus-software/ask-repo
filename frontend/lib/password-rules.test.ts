import { describe, expect, it } from "vitest";

import { checkPassword, passwordChecksPass } from "@/lib/password-rules";

const policy = { minLength: 12, maxBytes: 72 };

describe("checkPassword", () => {
  it("reports the length rule against the policy it was given, not a hard-coded one", () => {
    const strict = checkPassword("abcdefghijkl", { minLength: 16, maxBytes: 72 });
    expect(strict.find((c) => c.id === "minLength")?.passed).toBe(false);
    expect(strict.find((c) => c.id === "minLength")?.label).toContain("16");
  });

  it("passes the length rule at exactly the minimum", () => {
    expect(
      checkPassword("a".repeat(12), policy).find((c) => c.id === "minLength")?.passed,
    ).toBe(true);
  });

  it("measures the byte cap in UTF-8, not characters", () => {
    // An emoji is four bytes, so 20 of them exceed 72 bytes while being 20 characters.
    const value = "😀".repeat(20);
    expect(value.length).toBeLessThan(policy.maxBytes);
    expect(checkPassword(value, policy).find((c) => c.id === "maxBytes")?.passed).toBe(
      false,
    );
  });

  it("hides the byte cap while it is satisfied, since it is noise for a normal password", () => {
    expect(checkPassword("a".repeat(12), policy).some((c) => c.id === "maxBytes")).toBe(
      false,
    );
  });
});

describe("passwordChecksPass", () => {
  it("is false for an empty value", () => {
    expect(passwordChecksPass("", policy)).toBe(false);
  });

  it("is true once every local check passes", () => {
    expect(passwordChecksPass("a-long-enough-passphrase", policy)).toBe(true);
  });

  it("is false when the byte cap is exceeded", () => {
    expect(passwordChecksPass("😀".repeat(20), policy)).toBe(false);
  });
});

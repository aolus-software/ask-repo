import { describe, expect, it } from "vitest";

import { nextDelay } from "@/lib/live/backoff";

describe("nextDelay", () => {
  it("starts at one second and doubles", () => {
    const noJitter = () => 0.5;
    expect(nextDelay(0, noJitter)).toBe(1000);
    expect(nextDelay(1, noJitter)).toBe(2000);
    expect(nextDelay(3, noJitter)).toBe(8000);
  });

  it("caps at sixty seconds", () => {
    expect(nextDelay(20, () => 0.5)).toBe(60_000);
  });

  it("jitters by up to a fifth either way", () => {
    expect(nextDelay(2, () => 0)).toBe(3200);
    expect(nextDelay(2, () => 1)).toBe(4800);
  });
});

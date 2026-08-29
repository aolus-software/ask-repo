import { describe, expect, it } from "vitest";

describe("test infrastructure", () => {
  it("runs and resolves the @/ alias", async () => {
    const mod = await import("@/lib/marker");
    expect(mod.MARKER).toBe("ok");
  });
});

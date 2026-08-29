import { describe, expect, it } from "vitest";

import { safeNext } from "@/lib/safe-next";

describe("safeNext", () => {
  it("keeps a same-origin absolute path", () => {
    expect(safeNext("/projects")).toBe("/projects");
    expect(safeNext("/projects?page=2")).toBe("/projects?page=2");
  });

  it("rejects a protocol-relative URL, which browsers treat as another origin", () => {
    expect(safeNext("//evil.example.com")).toBe("/");
  });

  it("rejects an absolute URL", () => {
    expect(safeNext("https://evil.example.com/steal")).toBe("/");
    expect(safeNext("javascript:alert(1)")).toBe("/");
  });

  it("rejects a relative path with no leading slash", () => {
    expect(safeNext("projects")).toBe("/");
  });

  it("falls back to the dashboard for null or empty", () => {
    expect(safeNext(null)).toBe("/");
    expect(safeNext("")).toBe("/");
  });
});

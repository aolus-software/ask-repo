import { describe, expect, it } from "vitest";

import { canManageProject } from "@/lib/can";

const project = { createdBy: "user-a" };

describe("canManageProject", () => {
  it("allows the creator", () => {
    expect(canManageProject({ id: "user-a", isAdmin: false }, project)).toBe(true);
  });

  it("allows any admin", () => {
    expect(canManageProject({ id: "user-b", isAdmin: true }, project)).toBe(true);
  });

  it("refuses a different non-admin user", () => {
    expect(canManageProject({ id: "user-b", isAdmin: false }, project)).toBe(false);
  });
});

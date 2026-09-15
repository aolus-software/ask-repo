import { describe, expect, it } from "vitest";

import { PERMISSION, can } from "@/lib/can";

describe("can", () => {
  it("is true when the server granted the permission", () => {
    const project = { permissions: [PERMISSION.PROJECT_DELETE] };

    expect(can(project, PERMISSION.PROJECT_DELETE)).toBe(true);
  });

  it("is false when it did not", () => {
    const project = { permissions: [PERMISSION.PROJECT_READ] };

    expect(can(project, PERMISSION.PROJECT_DELETE)).toBe(false);
  });

  it("is false for a project with no permissions at all", () => {
    // A non-member never reaches this — the API returns 404 — but a defensive
    // false is the right answer if one ever does.
    expect(can({ permissions: [] }, PERMISSION.PROJECT_READ)).toBe(false);
  });

  it("does not infer one permission from another", () => {
    // No hierarchy on the client. The server sends the effective set; the client
    // does not reconstruct a role's meaning, which is what lets a runtime-created
    // custom role work with no frontend release.
    const project = { permissions: [PERMISSION.PROJECT_DELETE] };

    expect(can(project, PERMISSION.PROJECT_READ)).toBe(false);
  });
});

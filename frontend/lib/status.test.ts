import { describe, expect, it } from "vitest";

import type { ProjectStatus } from "@/lib/api/types";
import { isTerminalStatus, statusLabel, statusTone } from "@/lib/status";

const ALL: ProjectStatus[] = ["pending", "cloning", "indexing", "ready", "failed"];

describe("statusTone", () => {
  it("maps every status to exactly one semantic tone", () => {
    expect(ALL.map(statusTone)).toEqual([
      "warning",
      "warning",
      "warning",
      "success",
      "danger",
    ]);
  });

  it("covers every status with no fallthrough", () => {
    for (const status of ALL) {
      expect(["success", "warning", "danger"]).toContain(statusTone(status));
    }
  });
});

describe("statusLabel", () => {
  it("gives every status a human label", () => {
    expect(statusLabel("ready")).toBe("Ready");
    expect(statusLabel("failed")).toBe("Failed");
    expect(ALL.every((s) => statusLabel(s).length > 0)).toBe(true);
  });
});

describe("isTerminalStatus", () => {
  it("treats only ready and failed as settled", () => {
    expect(ALL.filter(isTerminalStatus)).toEqual(["ready", "failed"]);
  });
});

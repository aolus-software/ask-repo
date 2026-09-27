import { describe, expect, it } from "vitest";

import type { ChecklistItemStatus, ProjectStatus } from "@/lib/api/types";
import {
  auditOutcomeLabel,
  auditOutcomeTone,
  checklistItemResultLabel,
  checklistItemResultTone,
  isTerminalStatus,
  statusLabel,
  statusTone,
} from "@/lib/status";

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

const RESULTS: ChecklistItemStatus[] = ["untested", "pass", "fail", "blocked"];

describe("checklistItemResultTone", () => {
  it("gives blocked a warning, not a danger", () => {
    expect(checklistItemResultTone("blocked")).toBe("warning");
    expect(checklistItemResultTone("fail")).toBe("danger");
    expect(checklistItemResultTone("pass")).toBe("success");
  });

  it("covers every result with no fallthrough", () => {
    for (const status of RESULTS) {
      expect(["success", "warning", "danger", "neutral"]).toContain(
        checklistItemResultTone(status),
      );
    }
  });
});

describe("checklistItemResultLabel", () => {
  it("gives every result a human label", () => {
    expect(RESULTS.every((s) => checklistItemResultLabel(s).length > 0)).toBe(true);
  });
});

describe("auditOutcomeTone/auditOutcomeLabel", () => {
  it("maps the two-value outcome domain", () => {
    expect(auditOutcomeTone("failure")).toBe("danger");
    expect(auditOutcomeTone("success")).toBe("success");
    expect(auditOutcomeLabel("failure")).toBe("Failure");
    expect(auditOutcomeLabel("success")).toBe("Success");
  });
});

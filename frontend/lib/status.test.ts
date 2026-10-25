import { describe, expect, it } from "vitest";

import type { ChecklistItemStatus, ProjectStatus } from "@/lib/api/types";
import {
  auditOutcomeLabelKey,
  auditOutcomeTone,
  changeSetOperationTone,
  evalAdvisoryTone,
  pendingChangeSetTone,
  testCaseKindTone,
  toneTextClass,
  checklistItemResultLabelKey,
  checklistItemResultTone,
  isTerminalStatus,
  statusLabelKey,
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

describe("statusLabelKey", () => {
  it("names a catalogue key for every status", () => {
    expect(statusLabelKey("ready")).toBe("project.ready");
    expect(statusLabelKey("failed")).toBe("project.failed");
    expect(ALL.every((s) => statusLabelKey(s).length > 0)).toBe(true);
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
    expect(RESULTS.every((s) => checklistItemResultLabelKey(s).length > 0)).toBe(true);
  });
});

describe("auditOutcomeTone/auditOutcomeLabelKey", () => {
  it("maps the two-value outcome domain", () => {
    expect(auditOutcomeTone("failure")).toBe("danger");
    expect(auditOutcomeTone("success")).toBe("success");
    expect(auditOutcomeLabelKey("failure")).toBe("auditOutcome.failure");
    expect(auditOutcomeLabelKey("success")).toBe("auditOutcome.success");
  });
});

describe("test-case, change-set and advisory tones", () => {
  it("tones a negative test case as a warning and a positive one as neutral", () => {
    expect(testCaseKindTone("negative")).toBe("warning");
    expect(testCaseKindTone("positive")).toBe("neutral");
  });

  it("tones each change-set operation", () => {
    expect(changeSetOperationTone("add")).toBe("success");
    expect(changeSetOperationTone("update")).toBe("neutral");
    expect(changeSetOperationTone("remove")).toBe("danger");
  });

  it("tones a pending change set and an eval advisory as warnings", () => {
    expect(pendingChangeSetTone()).toBe("warning");
    expect(evalAdvisoryTone()).toBe("warning");
  });

  it("renders a tone as running text through the semantic text tokens", () => {
    expect(toneTextClass("success")).toBe("text-success-text");
    expect(toneTextClass("warning")).toBe("text-warning-text");
    expect(toneTextClass("danger")).toBe("text-danger-text");
    expect(toneTextClass("neutral")).toBe("text-muted-foreground");
  });
});

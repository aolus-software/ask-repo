import { describe, expect, it } from "vitest";

import { groupByFeature, summariseOperations } from "@/lib/checklist/operations";
import type { ChangeOperation, ChecklistItemResponse } from "@/lib/api/types";

function item(
  feature: string,
  testName: string,
  position: number,
): ChecklistItemResponse {
  return {
    id: `${feature}-${position}`,
    moduleId: "m",
    projectId: "p",
    feature,
    testName,
    expectedResult: "e",
    currentResult: null,
    status: "untested",
    notes: null,
    citations: null,
    source: "generated",
    kind: "positive",
    position,
    createdBy: "u",
    reviewedBy: null,
    reviewedAt: null,
    createdAt: "2026-09-01T00:00:00Z",
    updatedAt: "2026-09-01T00:00:00Z",
  };
}

describe("groupByFeature", () => {
  it("keeps features in first-appearance order and items in position order", () => {
    const grouped = groupByFeature([
      item("Login", "second", 1),
      item("Register", "first", 0),
      item("Login", "first", 0),
    ]);

    expect(grouped.map((group) => group.feature)).toEqual(["Login", "Register"]);
    expect(grouped[0].items.map((row) => row.testName)).toEqual(["first", "second"]);
  });

  it("returns nothing for an empty grid rather than one empty group", () => {
    expect(groupByFeature([])).toEqual([]);
  });
});

describe("summariseOperations", () => {
  it("counts each kind so the banner can say what is waiting", () => {
    const operations: ChangeOperation[] = [
      { op: "add", id: "1", rationale: "r" },
      { op: "add", id: "2", rationale: "r" },
      { op: "update", id: "3", itemId: "i", rationale: "r" },
      { op: "remove", id: "4", itemId: "j", rationale: "r" },
    ];

    expect(summariseOperations(operations)).toEqual({
      added: 2,
      updated: 1,
      removed: 1,
    });
  });
});

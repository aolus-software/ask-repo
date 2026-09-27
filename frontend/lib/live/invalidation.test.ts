import { describe, expect, it } from "vitest";

import { ALL_LIVE_KEYS, keysToInvalidate } from "@/lib/live/invalidation";
import { keys } from "@/lib/query/keys";

describe("keysToInvalidate", () => {
  it("refetches every project query for a project event", () => {
    expect(keysToInvalidate({ kind: "project", id: "p1", projectId: "p1" })).toEqual([
      keys.projects.all,
    ]);
  });

  it("refetches the module, the module list and its change sets", () => {
    expect(keysToInvalidate({ kind: "checklist_module", id: "m1", projectId: "p1" })).toEqual([
      keys.checklistModules.detail("m1"),
      keys.checklistModules.all,
      keys.checklistChangeSets.forModule("m1"),
    ]);
  });

  it("refetches mock data by module id", () => {
    expect(keysToInvalidate({ kind: "mock_data", id: "m1", projectId: "p1" })).toEqual([
      keys.mockData.detail("m1"),
      keys.mockDataChangeSets.forModule("m1"),
    ]);
  });

  it("refetches the bell for a notification", () => {
    expect(keysToInvalidate({ kind: "notification", id: "e1", projectId: "p1" })).toEqual([
      keys.notifications.all,
    ]);
  });

  it("names every top-level live key for a full refetch", () => {
    expect(ALL_LIVE_KEYS).toEqual([
      keys.projects.all,
      keys.checklistModules.all,
      keys.checklistChangeSets.all,
      ["mock-data"],
      ["mock-data-change-sets"],
      keys.notifications.all,
    ]);
  });
});

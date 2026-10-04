import { describe, expect, it } from "vitest";

import {
  ALL_LIVE_KEYS,
  isInvalidatePayload,
  keysToInvalidate,
  type InvalidatePayload,
} from "@/lib/live/invalidation";
import { keys } from "@/lib/query/keys";

describe("keysToInvalidate", () => {
  it("refetches every project query for a project event", () => {
    expect(keysToInvalidate({ kind: "project", id: "p1", projectId: "p1" })).toEqual([
      keys.projects.all,
    ]);
  });

  it("refetches the module, the module list and its change sets", () => {
    expect(
      keysToInvalidate({ kind: "checklist_module", id: "m1", projectId: "p1" }),
    ).toEqual([
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
    expect(
      keysToInvalidate({ kind: "notification", id: "e1", projectId: "p1" }),
    ).toEqual([keys.notifications.all]);
  });

  it("names every top-level live key for a full refetch", () => {
    expect(ALL_LIVE_KEYS).toEqual([
      keys.projects.all,
      keys.checklistModules.all,
      keys.checklistChangeSets.all,
      ["mock-data"],
      ["mock-data-change-sets"],
      keys.notifications.all,
      keys.eval.all,
    ]);
  });

  it("refetches a set's list and detail for an eval_set event", () => {
    expect(keysToInvalidate({ kind: "eval_set", id: "s1", projectId: "p1" })).toEqual([
      keys.eval.sets("p1"),
      keys.eval.set("s1"),
    ]);
  });

  it("refetches the run, every run list and the set list for an eval_run event", () => {
    expect(keysToInvalidate({ kind: "eval_run", id: "r1", projectId: "p1" })).toEqual([
      keys.eval.run("r1"),
      keys.eval.allRuns,
      keys.eval.sets("p1"),
    ]);
  });

  it("invalidates nothing for a kind this build does not recognize", () => {
    expect(
      keysToInvalidate({
        kind: "future_kind" as InvalidatePayload["kind"],
        id: "x",
        projectId: null,
      }),
    ).toEqual([]);
  });
});

describe("isInvalidatePayload", () => {
  it("accepts a well-shaped payload", () => {
    expect(isInvalidatePayload({ kind: "project", id: "p1", projectId: "p1" })).toBe(
      true,
    );
  });

  it("rejects a non-object", () => {
    expect(isInvalidatePayload(null)).toBe(false);
    expect(isInvalidatePayload("project")).toBe(false);
    expect(isInvalidatePayload(42)).toBe(false);
  });

  it("rejects an object missing a string kind or id", () => {
    expect(isInvalidatePayload({ id: "p1" })).toBe(false);
    expect(isInvalidatePayload({ kind: "project" })).toBe(false);
    expect(isInvalidatePayload({ kind: 1, id: "p1" })).toBe(false);
  });
});

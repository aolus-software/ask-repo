import { describe, expect, it } from "vitest";

import type { NotificationSummary } from "@/lib/api/types";
import { NOTIFICATION_TYPES, notificationHref, notificationTitle } from "@/lib/notifications";

const base: NotificationSummary = {
  id: "n1",
  createdAt: "2026-09-20T10:00:00Z",
  readAt: null,
  eventType: "project.ready",
  projectId: "p1",
  targetType: "project",
  targetId: "p1",
  actorUserId: null,
  details: {},
};

describe("notificationHref", () => {
  it("sends project events to the project", () => {
    expect(notificationHref({ ...base, eventType: "project.ready" })).toBe("/projects/p1");
  });

  it("sends both change-set families to the module screen", () => {
    const checklist = { ...base, eventType: "checklist_change_set.pending", targetType: "checklist_module", targetId: "m1" };
    const mockData = { ...base, eventType: "mock_data_change_set.pending", targetType: "checklist_module", targetId: "m1" };
    expect(notificationHref(checklist)).toBe("/checklist/m1");
    expect(notificationHref(mockData)).toBe("/checklist/m1");
  });

  it("falls back to the project when the target id is missing", () => {
    expect(notificationHref({ ...base, eventType: "project.ready", targetId: null })).toBe("/projects/p1");
  });
});

describe("notificationTitle", () => {
  it("names the project for an index outcome", () => {
    const title = notificationTitle({ ...base, eventType: "project.ready", details: { projectName: "api" } });
    expect(title).toContain("api");
  });

  it("renders an unknown event type without throwing", () => {
    expect(() => notificationTitle({ ...base, eventType: "future.event" })).not.toThrow();
  });
});

describe("NOTIFICATION_TYPES", () => {
  it("has no duplicates", () => {
    expect(new Set(NOTIFICATION_TYPES).size).toBe(NOTIFICATION_TYPES.length);
  });
});

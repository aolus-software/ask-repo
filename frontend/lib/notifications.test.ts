import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import type { NotificationSummary } from "@/lib/api/types";
import {
  NOTIFICATION_TYPES,
  notificationHref,
  notificationTitle,
  notificationTitleForType,
} from "@/lib/notifications";
import en from "@/messages/en/index";

const t = createTranslator({ locale: "en", messages: en, namespace: "notifications" });

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
    expect(notificationHref({ ...base, eventType: "project.ready" })).toBe(
      "/projects/p1",
    );
  });

  it("sends both change-set families to the module screen", () => {
    const checklist = {
      ...base,
      eventType: "checklist_change_set.pending",
      targetType: "checklist_module",
      targetId: "m1",
    };
    const mockData = {
      ...base,
      eventType: "mock_data_change_set.pending",
      targetType: "checklist_module",
      targetId: "m1",
    };
    expect(notificationHref(checklist)).toBe("/checklist/m1");
    expect(notificationHref(mockData)).toBe("/checklist/m1");
  });

  it("sends both eval families to the set's screen", () => {
    for (const eventType of ["eval_set.ready", "eval_run.failed"]) {
      expect(
        notificationHref({
          ...base,
          eventType,
          targetType: "eval_set",
          targetId: "s1",
        }),
      ).toBe("/projects/p1/eval/s1");
    }
  });

  it("falls back to the project when the target id is missing", () => {
    expect(
      notificationHref({ ...base, eventType: "project.ready", targetId: null }),
    ).toBe("/projects/p1");
  });
});

describe("notificationTitle", () => {
  it("names the project for an index outcome", () => {
    const title = notificationTitle(
      {
        ...base,
        eventType: "project.ready",
        details: { projectName: "api" },
      },
      t,
    );
    expect(title).toContain("api");
  });

  it("names the set and the project for an eval outcome", () => {
    const title = notificationTitle(
      {
        ...base,
        eventType: "eval_run.finished",
        details: { projectName: "api", setName: "auth paths" },
      },
      t,
    );
    expect(title).toContain("auth paths");
    expect(title).toContain("api");
  });

  it("has a title and a category label for every known type", () => {
    for (const eventType of NOTIFICATION_TYPES) {
      expect(notificationTitle({ ...base, eventType }, t)).not.toBe(eventType);
      expect(notificationTitleForType(eventType, t)).not.toBe(eventType);
    }
  });

  it("renders an unknown event type without throwing", () => {
    expect(() =>
      notificationTitle({ ...base, eventType: "future.event" }, t),
    ).not.toThrow();
  });
});

describe("notificationTitleForType", () => {
  it("labels the category, not one row", () => {
    expect(notificationTitleForType("project.ready", t)).toBe(
      "A project finished indexing",
    );
  });

  it("renders an unknown event type without throwing", () => {
    expect(() => notificationTitleForType("future.event", t)).not.toThrow();
    expect(notificationTitleForType("future.event", t)).toBe("future.event");
  });
});

describe("NOTIFICATION_TYPES", () => {
  it("has no duplicates", () => {
    expect(new Set(NOTIFICATION_TYPES).size).toBe(NOTIFICATION_TYPES.length);
  });
});

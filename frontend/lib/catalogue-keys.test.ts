import { describe, expect, it } from "vitest";

import type {
  AuditOutcome,
  ChecklistItemStatus,
  ChecklistModuleStatus,
  EvalRunStatus,
  EvalSetStatus,
  EvalVerdict,
  ProjectStatus,
} from "@/lib/api/types";
import { AUDIT_EVENT_TYPES } from "@/lib/audit";
import { NOTIFICATION_TYPES } from "@/lib/notifications";
import {
  auditOutcomeLabelKey,
  checklistItemResultLabelKey,
  checklistModuleStatusLabelKey,
  evalStatusLabelKey,
  evalVerdictLabelKey,
  statusLabelKey,
} from "@/lib/status";
import en from "@/messages/en/index";

/** Resolve a dotted key against the English catalogue. */
function lookup(tree: unknown, key: string): unknown {
  return key
    .split(".")
    .reduce<unknown>(
      (node, part) =>
        node && typeof node === "object"
          ? (node as Record<string, unknown>)[part]
          : undefined,
      tree,
    );
}

const PROJECT: ProjectStatus[] = ["pending", "cloning", "indexing", "ready", "failed"];
const MODULE: ChecklistModuleStatus[] = [
  "empty",
  "generating",
  "review",
  "ready",
  "failed",
];
const RESULT: ChecklistItemStatus[] = ["untested", "pass", "fail", "blocked"];
const OUTCOME: AuditOutcome[] = ["success", "failure"];
const EVAL_STATUS: (EvalSetStatus | EvalRunStatus)[] = [
  "generating",
  "running",
  "ready",
  "done",
  "failed",
];
const VERDICT: EvalVerdict[] = ["correct", "partial", "wrong", "error"];

describe("lib/status.ts label keys", () => {
  const cases: [string, string[]][] = [
    ["project", PROJECT.map(statusLabelKey)],
    ["module", MODULE.map(checklistModuleStatusLabelKey)],
    ["result", RESULT.map(checklistItemResultLabelKey)],
    ["auditOutcome", OUTCOME.map(auditOutcomeLabelKey)],
    ["evalStatus", EVAL_STATUS.map(evalStatusLabelKey)],
    ["evalVerdict", VERDICT.map(evalVerdictLabelKey)],
  ];

  it.each(cases)("every %s key exists in messages/en/status.json", (_domain, keys) => {
    for (const key of keys) {
      expect(typeof lookup(en.status, key), key).toBe("string");
    }
  });

  it("the catalogue has no status label the functions cannot return", () => {
    const returnable = new Set(cases.flatMap(([, keys]) => keys));
    const catalogue = Object.entries(en.status).flatMap(([group, labels]) =>
      Object.keys(labels as object).map((name) => `${group}.${name}`),
    );
    expect(catalogue.filter((key) => !returnable.has(key))).toEqual([]);
  });
});

describe("event vocabularies", () => {
  it("every notification type has a notifications.types entry", () => {
    for (const type of NOTIFICATION_TYPES) {
      const key = type.replaceAll(".", "_");
      expect(typeof lookup(en.notifications, `types.${key}`), type).toBe("string");
    }
  });

  it("every audit event type has an audit.events entry", () => {
    for (const type of AUDIT_EVENT_TYPES) {
      const key = type.replaceAll(".", "_");
      expect(typeof lookup(en.audit, `events.${key}`), type).toBe("string");
    }
  });
});

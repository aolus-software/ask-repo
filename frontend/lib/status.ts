import type {
  AuditOutcome,
  EvalRunStatus,
  EvalVerdict,
  EvalSetStatus,
  ChecklistItemKind,
  ChecklistItemStatus,
  ChecklistModuleStatus,
  ProjectStatus,
} from "@/lib/api/types";

/**
 * The single status → colour mapping (`.claude/rules/design-system.md` §5). A badge,
 * a table row and a detail header showing the same state must agree, so no component
 * picks a colour of its own.
 *
 * Labels are message keys under the `status` namespace, not English: a caller
 * translates with `useTranslations("status")`, so the key lives here beside its tone
 * and the words live in `messages/en/status.json`.
 *
 * `info` has one job in this app: a role or a neutral advisory that is not a status at
 * all (`docs/audit-finding-solved-logs.md` §U1.2, §U4.1) — never a project or module state.
 */
export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

const PROJECT_TONES: Record<ProjectStatus, StatusTone> = {
  pending: "warning",
  cloning: "warning",
  indexing: "warning",
  ready: "success",
  failed: "danger",
};

export function statusTone(status: ProjectStatus): StatusTone {
  return PROJECT_TONES[status];
}

export function statusLabelKey(status: ProjectStatus): `project.${ProjectStatus}` {
  return `project.${status}`;
}

/** Settled states. Anything else is still moving, so the list keeps polling. */
export function isTerminalStatus(status: ProjectStatus): boolean {
  return status === "ready" || status === "failed";
}

/**
 * Same mapping, same file, for the checklist module's own status vocabulary — moved
 * here from `components/checklist/module-status-badge.tsx` so both status domains are
 * provably named in one module rather than one in `lib/` and one in `components/`
 * (`docs/audit-finding-solved-logs.md` §U4.1).
 */
const MODULE_TONES: Record<ChecklistModuleStatus, StatusTone> = {
  empty: "neutral",
  generating: "warning",
  // A module with a proposal waiting is not finished, and showing it green would say
  // it was. `review` is the state the whole feature exists to make visible.
  review: "warning",
  ready: "success",
  failed: "danger",
};

export function checklistModuleStatusTone(status: ChecklistModuleStatus): StatusTone {
  return MODULE_TONES[status];
}

export function checklistModuleStatusLabelKey(
  status: ChecklistModuleStatus,
): `module.${ChecklistModuleStatus}` {
  return `module.${status}`;
}

/**
 * A checklist item's recorded result — a third status domain, moved here from
 * `components/checklist/item-grid.tsx` so it is provably named in one module
 * rather than re-derived at the next call site that needs this state's colour
 * (`docs/audit-finding-solved-logs.md` §U4.4).
 *
 * `blocked` is a warning, not a danger. "Could not run this" is a different finding
 * from "this behaved wrongly", and colouring them alike is how a blocked test ends up
 * recorded as a failure and the pass rate stops meaning anything.
 */
const RESULT_TONES: Record<ChecklistItemStatus, StatusTone> = {
  untested: "neutral",
  pass: "success",
  fail: "danger",
  blocked: "warning",
};

export function checklistItemResultTone(status: ChecklistItemStatus): StatusTone {
  return RESULT_TONES[status];
}

export function checklistItemResultLabelKey(
  status: ChecklistItemStatus,
): `result.${ChecklistItemStatus}` {
  return `result.${status}`;
}

/**
 * The audit trail's two-value outcome domain (`docs/audit-finding-solved-logs.md` §U4.6).
 * Every row is `success` or `failure`; a badge showing it must never pick the
 * colour at the call site, the same rule the project and module mappings above
 * already follow.
 */
export function auditOutcomeTone(outcome: AuditOutcome): StatusTone {
  return outcome === "failure" ? "danger" : "success";
}

export function auditOutcomeLabelKey(
  outcome: AuditOutcome,
): "auditOutcome.failure" | "auditOutcome.success" {
  return outcome === "failure" ? "auditOutcome.failure" : "auditOutcome.success";
}

/**
 * The eval harness's two status vocabularies. A set is `generating` → `ready` / `failed`
 * and a run `running` → `done` / `failed`; both pair a moving state with `warning`, a
 * settled good one with `success` and a failure with `danger`, like every domain above.
 */
const EVAL_STATUS_TONES: Record<EvalSetStatus | EvalRunStatus, StatusTone> = {
  generating: "warning",
  running: "warning",
  ready: "success",
  done: "success",
  failed: "danger",
};

export function evalStatusTone(status: EvalSetStatus | EvalRunStatus): StatusTone {
  return EVAL_STATUS_TONES[status];
}

export function evalStatusLabelKey(
  status: EvalSetStatus | EvalRunStatus,
): `evalStatus.${EvalSetStatus | EvalRunStatus}` {
  return `evalStatus.${status}`;
}

const EVAL_VERDICT_TONES: Record<EvalVerdict, StatusTone> = {
  correct: "success",
  partial: "warning",
  wrong: "danger",
  error: "neutral",
};

export function evalVerdictTone(verdict: EvalVerdict): StatusTone {
  return EVAL_VERDICT_TONES[verdict];
}

export function evalVerdictLabelKey(
  verdict: EvalVerdict,
): `evalVerdict.${EvalVerdict}` {
  return `evalVerdict.${verdict}`;
}

/**
 * A test case's kind. Only negatives are badged (`components/checklist/item-grid.tsx`),
 * so `positive` is `neutral`, the tone of "nothing to flag" (`docs/audit-findings.md` §U4.7).
 */
const TEST_CASE_KIND_TONES: Record<ChecklistItemKind, StatusTone> = {
  positive: "neutral",
  negative: "warning",
};

export function testCaseKindTone(kind: ChecklistItemKind): StatusTone {
  return TEST_CASE_KIND_TONES[kind];
}

/**
 * The three operations of a pending change set. An addition is the good news, a
 * removal is the one that destroys something, and a change is neither.
 */
export type ChangeSetOperationKind = "add" | "update" | "remove";

const CHANGE_SET_OPERATION_TONES: Record<ChangeSetOperationKind, StatusTone> = {
  add: "success",
  update: "neutral",
  remove: "danger",
};

export function changeSetOperationTone(op: ChangeSetOperationKind): StatusTone {
  return CHANGE_SET_OPERATION_TONES[op];
}

/**
 * A change set that is waiting for a human. It is not finished, which is why it
 * shares `warning` with the module's own `review` status.
 */
export function pendingChangeSetTone(): StatusTone {
  return "warning";
}

/**
 * An advisory on an eval pair or result (an unfaithful translation, a grounding
 * warning): worth reading, not a failure.
 */
export function evalAdvisoryTone(): StatusTone {
  return "warning";
}

/**
 * The same tones as running text, for a heading or a count that is not a badge.
 * `StatusBadge` owns the filled form; this is its inline twin, so neither is picked
 * at a call site.
 */
const TONE_TEXT_CLASSES: Record<StatusTone, string> = {
  success: "text-success-text",
  warning: "text-warning-text",
  danger: "text-danger-text",
  neutral: "text-muted-foreground",
  info: "text-primary",
};

export function toneTextClass(tone: StatusTone): string {
  return TONE_TEXT_CLASSES[tone];
}

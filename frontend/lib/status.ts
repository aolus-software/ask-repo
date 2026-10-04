import type {
  AuditOutcome,
  EvalRunStatus,
  EvalSetStatus,
  ChecklistItemStatus,
  ChecklistModuleStatus,
  ProjectStatus,
} from "@/lib/api/types";

/**
 * The single status → colour mapping (`.claude/rules/design-system.md` §5). A badge,
 * a table row and a detail header showing the same state must agree, so no component
 * picks a colour of its own.
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

const PROJECT_LABELS: Record<ProjectStatus, string> = {
  pending: "Pending",
  cloning: "Cloning",
  indexing: "Indexing",
  ready: "Ready",
  failed: "Failed",
};

export function statusTone(status: ProjectStatus): StatusTone {
  return PROJECT_TONES[status];
}

export function statusLabel(status: ProjectStatus): string {
  return PROJECT_LABELS[status];
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

const MODULE_LABELS: Record<ChecklistModuleStatus, string> = {
  empty: "Empty",
  generating: "Generating",
  review: "Review",
  ready: "Ready",
  failed: "Failed",
};

export function checklistModuleStatusTone(status: ChecklistModuleStatus): StatusTone {
  return MODULE_TONES[status];
}

export function checklistModuleStatusLabel(status: ChecklistModuleStatus): string {
  return MODULE_LABELS[status];
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

const RESULT_LABELS: Record<ChecklistItemStatus, string> = {
  untested: "Untested",
  pass: "Pass",
  fail: "Fail",
  blocked: "Blocked",
};

export function checklistItemResultTone(status: ChecklistItemStatus): StatusTone {
  return RESULT_TONES[status];
}

export function checklistItemResultLabel(status: ChecklistItemStatus): string {
  return RESULT_LABELS[status];
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

export function auditOutcomeLabel(outcome: AuditOutcome): string {
  return outcome === "failure" ? "Failure" : "Success";
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

const EVAL_STATUS_LABELS: Record<EvalSetStatus | EvalRunStatus, string> = {
  generating: "Generating",
  running: "Running",
  ready: "Ready",
  done: "Done",
  failed: "Failed",
};

export function evalStatusTone(status: EvalSetStatus | EvalRunStatus): StatusTone {
  return EVAL_STATUS_TONES[status];
}

export function evalStatusLabel(status: EvalSetStatus | EvalRunStatus): string {
  return EVAL_STATUS_LABELS[status];
}

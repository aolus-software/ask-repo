import type { ChecklistModuleStatus, ProjectStatus } from "@/lib/api/types";

/**
 * The single status → colour mapping (`.claude/rules/design-system.md` §5). A badge,
 * a table row and a detail header showing the same state must agree, so no component
 * picks a colour of its own.
 *
 * `info` has one job in this app: a role or a neutral advisory that is not a status at
 * all (`docs/ui-audit-findings.md` §U1.2, §U4.1) — never a project or module state.
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
 * (`docs/ui-audit-findings.md` §U4.1).
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

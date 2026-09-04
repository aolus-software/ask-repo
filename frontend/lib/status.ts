import type { ProjectStatus } from "@/lib/api/types";

/**
 * The single status → colour mapping (`.claude/rules/design-system.md` §5). A badge,
 * a table row and a detail header showing the same state must agree, so no component
 * picks a colour of its own.
 */
export type StatusTone = "success" | "warning" | "danger" | "neutral";

const TONES: Record<ProjectStatus, StatusTone> = {
  pending: "warning",
  cloning: "warning",
  indexing: "warning",
  ready: "success",
  failed: "danger",
};

const LABELS: Record<ProjectStatus, string> = {
  pending: "Pending",
  cloning: "Cloning",
  indexing: "Indexing",
  ready: "Ready",
  failed: "Failed",
};

export function statusTone(status: ProjectStatus): StatusTone {
  return TONES[status];
}

export function statusLabel(status: ProjectStatus): string {
  return LABELS[status];
}

/** Settled states. Anything else is still moving, so the list keeps polling. */
export function isTerminalStatus(status: ProjectStatus): boolean {
  return status === "ready" || status === "failed";
}

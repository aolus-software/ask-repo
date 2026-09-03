import { StatusBadge } from "@/components/feedback/status-badge";
import type { ChecklistModuleStatus } from "@/lib/api/types";
import type { StatusTone } from "@/lib/status";

const LABELS: Record<ChecklistModuleStatus, string> = {
  empty: "Empty",
  generating: "Generating",
  review: "Review",
  ready: "Ready",
  failed: "Failed",
};

const TONES: Record<ChecklistModuleStatus, StatusTone> = {
  empty: "neutral",
  generating: "warning",
  // A module with a proposal waiting is not finished, and showing it green would say
  // it was. `review` is the state the whole feature exists to make visible.
  review: "warning",
  ready: "success",
  failed: "danger",
};

/**
 * One mapping, used by the module list and the module screen alike.
 *
 * Extracted rather than repeated: two copies drift, and the pair that drifts first is
 * always the one where a status means "needs a human" on one screen and "done" on the
 * other.
 */
export function ChecklistModuleStatusBadge({
  status,
  className,
}: {
  status: ChecklistModuleStatus;
  className?: string;
}) {
  return (
    <StatusBadge tone={TONES[status]} label={LABELS[status]} className={className} />
  );
}

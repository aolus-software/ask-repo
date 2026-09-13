import { StatusBadge } from "@/components/feedback/status-badge";
import type { ChecklistModuleStatus } from "@/lib/api/types";
import { checklistModuleStatusLabel, checklistModuleStatusTone } from "@/lib/status";

/**
 * One mapping, used by the module list and the module screen alike. The mapping
 * itself lives in `lib/status.ts` beside the project one
 * (`docs/ui-audit-findings.md` §U4.1) — this stays a thin renderer so both status
 * domains are provably named in one file.
 */
export function ChecklistModuleStatusBadge({
  status,
  className,
}: {
  status: ChecklistModuleStatus;
  className?: string;
}) {
  return (
    <StatusBadge
      tone={checklistModuleStatusTone(status)}
      label={checklistModuleStatusLabel(status)}
      className={className}
    />
  );
}

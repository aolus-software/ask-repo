import { StatusBadge } from "@/components/feedback/status-badge";
import type { EvalVerdict } from "@/lib/api/types";
import { evalVerdictLabel, evalVerdictTone } from "@/lib/status";

export function EvalVerdictBadge({ verdict }: { verdict: EvalVerdict }) {
  return (
    <StatusBadge tone={evalVerdictTone(verdict)} label={evalVerdictLabel(verdict)} />
  );
}

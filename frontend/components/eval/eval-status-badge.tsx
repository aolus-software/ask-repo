import { useTranslations } from "next-intl";

import { StatusBadge } from "@/components/feedback/status-badge";
import type { EvalRunStatus, EvalSetStatus } from "@/lib/api/types";
import { evalStatusLabelKey, evalStatusTone } from "@/lib/status";

/** One renderer for a set's status and a run's; the mapping lives in `lib/status.ts`. */
export function EvalStatusBadge({
  status,
  className,
}: {
  status: EvalSetStatus | EvalRunStatus;
  className?: string;
}) {
  const t = useTranslations("status");
  return (
    <StatusBadge
      tone={evalStatusTone(status)}
      label={t(evalStatusLabelKey(status))}
      className={className}
    />
  );
}

import { useTranslations } from "next-intl";

import { StatusBadge } from "@/components/feedback/status-badge";
import type { EvalVerdict } from "@/lib/api/types";
import { evalVerdictLabelKey, evalVerdictTone } from "@/lib/status";

export function EvalVerdictBadge({ verdict }: { verdict: EvalVerdict }) {
  const t = useTranslations("status");
  return (
    <StatusBadge
      tone={evalVerdictTone(verdict)}
      label={t(evalVerdictLabelKey(verdict))}
    />
  );
}

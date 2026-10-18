import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import type { ProjectStatus } from "@/lib/api/types";
import { type StatusTone, statusLabelKey, statusTone } from "@/lib/status";
import { cn } from "@/lib/utils";

/**
 * Status renders as a Badge with the semantic colour, never a coloured dot alone
 * (`docs/design.md` → Lists) — a dot carries meaning no label repeats.
 */
const TONE_CLASSES: Record<StatusTone, string> = {
  success: "bg-success text-success-foreground",
  warning: "bg-warning text-warning-foreground",
  danger: "bg-danger text-danger-foreground",
  neutral: "bg-muted text-muted-foreground",
  info: "bg-info text-info-foreground",
};

export function StatusBadge({
  tone,
  label,
  className,
}: {
  tone: StatusTone;
  label: string;
  className?: string;
}) {
  return <Badge className={cn(TONE_CLASSES[tone], className)}>{label}</Badge>;
}

/** The project-status spelling, so existing callers keep their one-argument shape. */
export function ProjectStatusBadge({
  status,
  className,
}: {
  status: ProjectStatus;
  className?: string;
}) {
  const t = useTranslations("status");
  return (
    <StatusBadge
      tone={statusTone(status)}
      label={t(statusLabelKey(status))}
      className={className}
    />
  );
}

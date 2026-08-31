import { Badge } from "@/components/ui/badge";
import type { ProjectStatus } from "@/lib/api/types";
import { type StatusTone, statusLabel, statusTone } from "@/lib/status";
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
  return (
    <StatusBadge
      tone={statusTone(status)}
      label={statusLabel(status)}
      className={className}
    />
  );
}

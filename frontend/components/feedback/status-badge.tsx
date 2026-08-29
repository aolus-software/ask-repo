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
};

export function StatusBadge({ status, className }: { status: ProjectStatus; className?: string }) {
  return (
    <Badge className={cn(TONE_CLASSES[statusTone(status)], className)}>{statusLabel(status)}</Badge>
  );
}

import type { LucideIcon } from "lucide-react";

import { CenteredMessage } from "@/components/feedback/centered-message";

/**
 * An empty list shows this with the primary action, never a bare "No results".
 *
 * `size="compact"` drops the icon and title for a narrow surface — a chat panel, a
 * sidebar rail — where the full treatment does not fit (`docs/ui-audit-findings.md`
 * §U2.2).
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  size = "default",
}: {
  icon?: LucideIcon;
  title?: string;
  description: string;
  action?: React.ReactNode;
  size?: "default" | "compact";
}) {
  return (
    <CenteredMessage
      icon={icon}
      level={3}
      title={title}
      description={description}
      action={action}
      compact={size === "compact"}
    />
  );
}

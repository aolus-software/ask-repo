import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The shared "centred icon, heading, body" panel behind `EmptyState`, `Forbidden` and
 * `NotFound` (`.claude/rules/design-system.md` §5's one-mapping rule, applied to full
 * panel messages instead of a status colour).
 *
 * `level` is chosen by the caller, never inferred: `2` when the message replaces a
 * page body (`Forbidden`, `NotFound`), `3` when it sits inside a card (`EmptyState`).
 * `compact` drops the icon and title for a narrow surface — a sidebar rail, a chat
 * panel — where the full `py-12` treatment does not fit.
 */
export function CenteredMessage({
  icon: Icon,
  tone = "muted",
  level = 3,
  title,
  description,
  action,
  compact = false,
}: {
  icon?: LucideIcon;
  tone?: "muted" | "danger";
  level?: 2 | 3;
  title?: string;
  description: React.ReactNode;
  action?: React.ReactNode;
  compact?: boolean;
}) {
  const Heading = level === 2 ? "h2" : "h3";

  if (compact) {
    return (
      <div className="flex flex-col items-center gap-2 py-4 text-center">
        <p className="text-muted-foreground text-sm">{description}</p>
        {action ? <div className="mt-1">{action}</div> : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center">
      {Icon ? (
        <Icon
          className={cn(
            "size-8",
            tone === "danger" ? "text-danger" : "text-muted-foreground",
          )}
        />
      ) : null}
      {title ? <Heading className="text-xl font-semibold">{title}</Heading> : null}
      <p className="text-muted-foreground max-w-md text-base">{description}</p>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

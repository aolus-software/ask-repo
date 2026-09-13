import { cn } from "@/lib/utils";

/**
 * One page header, used by every screen (`docs/ui-audit-findings.md` §U2.1) — a list
 * screen's title-plus-action row, a detail screen's title-plus-badge-plus-actions row,
 * and the sticky title bar a streaming conversation pins under the navbar.
 *
 * `titleAddon` is a badge (or badge cluster) rendered beside the title, not below it.
 * `meta` is arbitrary content rendered below the title — richer than `description`,
 * for a screen that needs a link, an icon, or a badge there instead of plain text.
 * `sticky` swaps the ordinary `mb-6` spacing for the pinned-under-the-navbar treatment
 * a long-running answer needs, so the question being answered stays visible while it
 * scrolls.
 */
export function PageHeader({
  title,
  titleAddon,
  description,
  meta,
  action,
  sticky = false,
}: {
  title: string;
  titleAddon?: React.ReactNode;
  description?: React.ReactNode;
  meta?: React.ReactNode;
  action?: React.ReactNode;
  sticky?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-4",
        sticky
          ? "bg-background border-border sticky top-16 z-10 border-b pb-4"
          : "mb-6",
      )}
    >
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
          {titleAddon}
        </div>
        {description ? (
          <p className="text-muted-foreground mt-1 text-base">{description}</p>
        ) : null}
        {meta}
      </div>
      {action}
    </div>
  );
}

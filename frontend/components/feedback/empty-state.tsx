import type { LucideIcon } from "lucide-react";

/** An empty list shows this with the primary action, never a bare "No results". */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center">
      <Icon className="text-muted-foreground size-8" />
      <h3 className="text-xl font-semibold">{title}</h3>
      <p className="text-muted-foreground max-w-md text-base">{description}</p>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

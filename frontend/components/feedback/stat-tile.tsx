import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * A card holding one label and one big number, with an optional line under it. The
 * one tile every screen uses (`docs/design.md` -> Stat tiles), so the next one is not
 * a fourth variant. `loading` swaps the number for its skeleton in the same box.
 */
export function StatTile({
  label,
  value,
  hint,
  loading = false,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  loading?: boolean;
}) {
  return (
    <Card>
      <CardContent className="p-6">
        <p className="text-muted-foreground text-sm font-medium">{label}</p>
        {loading ? (
          <Skeleton className="mt-1 h-9 w-16" />
        ) : (
          <p className="mt-1 text-3xl font-semibold">{value}</p>
        )}
        {hint ? <p className="text-muted-foreground mt-1 text-xs">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

/** Placeholder shaped like a `StatTile`, for a grid whose labels are not known yet. */
export function StatTileSkeleton({ withHint = false }: { withHint?: boolean }) {
  return (
    <Card>
      <CardContent className="p-6">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="mt-1 h-9 w-16" />
        {withHint ? <Skeleton className="mt-1 h-4 w-28" /> : null}
      </CardContent>
    </Card>
  );
}

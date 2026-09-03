import { Badge } from "@/components/ui/badge";

/**
 * Shown when the checklist was built from an older index generation.
 *
 * A prompt, never a block. `indexed_generation` flags a stale *checklist*, not a stale
 * *result* — nothing detects that the code changed under a passing row (spec 11.2), so
 * the copy must not imply it does.
 *
 * Semantic tokens only. No `dark:` utility: the token already knows what dark means.
 */
export function StalenessBadge() {
  return (
    <Badge variant="outline" className="border-border text-muted-foreground">
      Reindexed since — consider regenerating
    </Badge>
  );
}

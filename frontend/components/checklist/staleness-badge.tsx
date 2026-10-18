import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/**
 * Shown when the checklist was built from an older index generation.
 *
 * A prompt, never a block. `indexed_generation` flags a stale *checklist*, not a stale
 * *result* — nothing detects that the code changed under a passing row (spec 11.2), so
 * the copy must not imply it does.
 *
 * The advice lives in a tooltip rather than the badge itself: a badge is a fixed-height
 * pill that cannot wrap, and "Reindexed since — consider regenerating" was several
 * times the width of the status badge it sits beside on every screen it appears
 * (`docs/audit-finding-solved-logs.md` §U11.2).
 *
 * Semantic tokens only. No `dark:` utility: the token already knows what dark means.
 */
export function StalenessBadge() {
  const t = useTranslations("checklist.stalenessBadge");
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Badge variant="outline" className="border-border text-muted-foreground">
            {t("label")}
          </Badge>
        }
      />
      <TooltipContent>{t("tooltip")}</TooltipContent>
    </Tooltip>
  );
}

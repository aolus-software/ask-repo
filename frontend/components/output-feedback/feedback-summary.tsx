import { useTranslations } from "next-intl";

import { StatTile, StatTileSkeleton } from "@/components/feedback/stat-tile";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { FeedbackFeature, FeedbackSummary as Summary } from "@/lib/api/types";

/** Every feature, in display order. The words live in `outputFeedback.features`. */
export const FEEDBACK_FEATURES: FeedbackFeature[] = [
  "answer",
  "refine_checklist",
  "refine_mock_data",
  "generate_checklist",
  "propose_checklist",
  "generate_mock_data",
  "propose_mock_data",
];

function downRate(up: number, down: number): string {
  const total = up + down;
  return total === 0 ? "—" : `${Math.round((down / total) * 100)}%`;
}

/**
 * Card-shaped placeholder matching `FeedbackSummary`'s own grid, so the layout does
 * not jump when the summary query resolves (`docs/design.md` → Lists) — the same
 * reasoning `TableSkeleton` follows for the list below it.
 */
export function FeedbackSummarySkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <StatTileSkeleton key={index} withHint />
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-6">
          <Skeleton className="h-32 w-full" />
        </Card>
        <Card className="p-6">
          <Skeleton className="h-32 w-full" />
        </Card>
      </div>
    </div>
  );
}

export function FeedbackSummary({ summary }: { summary: Summary }) {
  const t = useTranslations("outputFeedback");

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {summary.byFeature.map((row) => (
          <StatTile
            key={row.feature}
            label={t(`features.${row.feature}`)}
            value={downRate(row.up, row.down)}
            hint={t("summary.hint", { votes: row.up + row.down })}
          />
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("summary.feature")}</TableHead>
                <TableHead>{t("summary.reason")}</TableHead>
                <TableHead className="text-right">{t("summary.count")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.byReason.map((row) => (
                <TableRow key={`${row.feature}-${row.reasonCode}`}>
                  <TableCell>{t(`features.${row.feature}`)}</TableCell>
                  <TableCell>{t(`reasons.${row.reasonCode}`)}</TableCell>
                  <TableCell className="text-right">{row.count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>

        <Card className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("summary.feature")}</TableHead>
                <TableHead>{t("summary.promptVersion")}</TableHead>
                <TableHead className="text-right">{t("summary.votes")}</TableHead>
                <TableHead className="text-right">{t("summary.downVoted")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.byPromptVersion.map((row) => (
                <TableRow key={`${row.feature}:${row.promptVersion}`}>
                  <TableCell>{t(`features.${row.feature}`)}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {row.promptVersion}
                  </TableCell>
                  <TableCell className="text-right">{row.up + row.down}</TableCell>
                  <TableCell className="text-right">
                    {downRate(row.up, row.down)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>
      <p className="text-muted-foreground text-xs">{t("summary.versionNote")}</p>
    </div>
  );
}

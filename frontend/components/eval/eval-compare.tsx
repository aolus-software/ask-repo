import { useTranslations } from "next-intl";

import { EvalVerdictBadge } from "@/components/eval/eval-verdict-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import type { EvalPair, EvalRunDetail } from "@/lib/api/types";
import { compareRuns, type Tally } from "@/lib/eval-compare";

function TallyLine({ label, tally }: { label: string; tally: Tally }) {
  const t = useTranslations("eval.compare");
  return (
    <p className="text-sm">
      <span className="text-muted-foreground">{label}:</span>{" "}
      {t("tally", {
        hits: tally.hits,
        total: tally.total,
        correct: tally.correct,
        partial: tally.partial,
        wrong: tally.wrong,
        errors: tally.errors,
      })}
    </p>
  );
}

/** Two runs of the same set, compared on the pairs both answered. */
export function EvalCompare({
  base,
  head,
  pairs,
}: {
  base: EvalRunDetail;
  head: EvalRunDetail;
  pairs: EvalPair[];
}) {
  const t = useTranslations("eval.compare");
  const comparison = compareRuns(base, head);
  const questions = new Map(pairs.map((pair) => [pair.id, pair.question]));

  return (
    <div className="space-y-3">
      {comparison.judgeChanged ? (
        <Alert variant="warning">
          <AlertDescription>{t("judgeChanged")}</AlertDescription>
        </Alert>
      ) : null}
      <p className="text-muted-foreground text-sm">
        {t("comparedOn", { count: comparison.commonPairIds.length })}
      </p>
      <TallyLine label={t("base")} tally={comparison.base} />
      <TallyLine label={t("head")} tally={comparison.head} />
      {comparison.flips.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("noChange")}</p>
      ) : (
        <ul className="divide-border divide-y rounded-md border">
          {comparison.flips.map((flip) => (
            <li key={flip.pairId} className="flex flex-wrap items-center gap-3 p-3">
              <span className="min-w-0 flex-1 text-sm">
                {questions.get(flip.pairId) ?? flip.pairId}
              </span>
              {flip.hit ? (
                <span className="text-sm">
                  {t("retrievalChange", {
                    from: flip.hit[0] ? t("hit") : t("miss"),
                    to: flip.hit[1] ? t("hit") : t("miss"),
                  })}
                </span>
              ) : null}
              {flip.verdict ? (
                <span className="flex items-center gap-1">
                  <EvalVerdictBadge verdict={flip.verdict[0]} />→
                  <EvalVerdictBadge verdict={flip.verdict[1]} />
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

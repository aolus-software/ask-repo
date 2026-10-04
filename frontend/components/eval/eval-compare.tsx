import { EvalVerdictBadge } from "@/components/eval/eval-verdict-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import type { EvalPair, EvalRunDetail } from "@/lib/api/types";
import { compareRuns, type Tally } from "@/lib/eval-compare";

function TallyLine({ label, tally }: { label: string; tally: Tally }) {
  return (
    <p className="text-sm">
      <span className="text-muted-foreground">{label}:</span> hits {tally.hits}/
      {tally.total} · correct {tally.correct} · partial {tally.partial} · wrong{" "}
      {tally.wrong} · errors {tally.errors}
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
  const comparison = compareRuns(base, head);
  const questions = new Map(pairs.map((pair) => [pair.id, pair.question]));

  return (
    <div className="space-y-3">
      {comparison.judgeChanged ? (
        <Alert variant="warning">
          <AlertDescription>
            These runs were judged by different models. Verdict changes may reflect the
            judge, not the answers. Retrieval hits are unaffected.
          </AlertDescription>
        </Alert>
      ) : null}
      <p className="text-muted-foreground text-sm">
        Compared on {comparison.commonPairIds.length} pairs both runs answered
      </p>
      <TallyLine label="Base" tally={comparison.base} />
      <TallyLine label="Head" tally={comparison.head} />
      {comparison.flips.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No pair changed between these runs.
        </p>
      ) : (
        <ul className="divide-border divide-y rounded-md border">
          {comparison.flips.map((flip) => (
            <li key={flip.pairId} className="flex flex-wrap items-center gap-3 p-3">
              <span className="min-w-0 flex-1 text-sm">
                {questions.get(flip.pairId) ?? flip.pairId}
              </span>
              {flip.hit ? (
                <span className="text-sm">
                  Retrieval: {flip.hit[0] ? "hit" : "miss"} →{" "}
                  {flip.hit[1] ? "hit" : "miss"}
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

import type { EvalResult, EvalRunDetail, EvalVerdict } from "@/lib/api/types";

export interface Tally {
  hits: number;
  correct: number;
  partial: number;
  wrong: number;
  errors: number;
  total: number;
}

/** A pair whose retrieval hit or verdict differs; only the fields that changed are set. */
export interface Flip {
  pairId: string;
  hit?: [boolean, boolean];
  verdict?: [EvalVerdict, EvalVerdict];
}

export interface RunComparison {
  commonPairIds: string[];
  base: Tally;
  head: Tally;
  flips: Flip[];
  judgeChanged: boolean;
  /** The chat model, answer prompt version or judge prompt version differs. */
  otherStampsChanged: boolean;
}

function tally(results: EvalResult[]): Tally {
  const count = (verdict: EvalVerdict) =>
    results.filter((result) => result.verdict === verdict).length;
  return {
    hits: results.filter((result) => result.retrievalHit).length,
    correct: count("correct"),
    partial: count("partial"),
    wrong: count("wrong"),
    errors: count("error"),
    total: results.length,
  };
}

export interface CompareOptions {
  /**
   * Maps the head run's pair ids to the base run's, for comparing a translated set's run
   * with its source's (spec §3.6). Without it both runs are of the same set.
   */
  headToBase?: Map<string, string>;
}

/**
 * Compare two runs on the pairs both answered. With `headToBase`, head results are
 * keyed by their base pair id, so every id in the result is the base set's. A pair one run skipped (excluded since,
 * or added by a later set edit) has nothing to compare against, so it is left out of
 * both tallies rather than counted as a regression.
 */
export function compareRuns(
  base: EvalRunDetail,
  head: EvalRunDetail,
  options: CompareOptions = {},
): RunComparison {
  const { headToBase } = options;
  const baseById = new Map(base.results.map((result) => [result.pairId, result]));
  const headById = new Map<string, EvalResult>();
  for (const result of head.results) {
    const key = headToBase ? headToBase.get(result.pairId) : result.pairId;
    if (key) headById.set(key, result);
  }
  const commonPairIds = [...baseById.keys()].filter((id) => headById.has(id)).sort();

  const baseResults = commonPairIds.map((id) => baseById.get(id)!);
  const headResults = commonPairIds.map((id) => headById.get(id)!);

  const flips: Flip[] = [];
  commonPairIds.forEach((pairId, index) => {
    const before = baseResults[index];
    const after = headResults[index];
    const flip: Flip = { pairId };
    if (before.retrievalHit !== after.retrievalHit) {
      flip.hit = [before.retrievalHit, after.retrievalHit];
    }
    if (before.verdict !== after.verdict) {
      flip.verdict = [before.verdict, after.verdict];
    }
    if (flip.hit || flip.verdict) flips.push(flip);
  });

  return {
    commonPairIds,
    base: tally(baseResults),
    head: tally(headResults),
    flips,
    judgeChanged: base.judgeModel !== head.judgeModel,
    otherStampsChanged:
      base.chatModel !== head.chatModel ||
      base.promptVersion !== head.promptVersion ||
      base.judgePromptVersion !== head.judgePromptVersion,
  };
}

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

/**
 * Compare two runs on the pairs both answered. A pair one run skipped (excluded since,
 * or added by a later set edit) has nothing to compare against, so it is left out of
 * both tallies rather than counted as a regression.
 */
export function compareRuns(base: EvalRunDetail, head: EvalRunDetail): RunComparison {
  const baseById = new Map(base.results.map((result) => [result.pairId, result]));
  const headById = new Map(head.results.map((result) => [result.pairId, result]));
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
  };
}

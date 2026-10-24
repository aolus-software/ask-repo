import { describe, expect, it } from "vitest";

import { compareRuns } from "@/lib/eval-compare";
import type { EvalResult, EvalRunDetail } from "@/lib/api/types";

function result(
  pairId: string,
  hit: boolean,
  verdict: EvalResult["verdict"],
): EvalResult {
  return {
    id: `r-${pairId}`,
    pairId,
    retrievalHit: hit,
    verdict,
    judgeReason: null,
    answer: "",
    groundingWarnings: [],
    retrievalAttempts: 1,
  };
}

function run(judgeModel: string, results: EvalResult[]): EvalRunDetail {
  return { judgeModel, results } as EvalRunDetail;
}

describe("compareRuns", () => {
  it("compares only the pairs both runs answered", () => {
    const base = run("m", [result("a", true, "correct"), result("b", true, "wrong")]);
    const head = run("m", [
      result("b", false, "correct"),
      result("c", true, "correct"),
    ]);

    const comparison = compareRuns(base, head);

    expect(comparison.commonPairIds).toEqual(["b"]);
    expect(comparison.base.total).toBe(1);
    expect(comparison.flips).toEqual([
      { pairId: "b", hit: [true, false], verdict: ["wrong", "correct"] },
    ]);
  });

  it("flags a judge change", () => {
    expect(compareRuns(run("a", []), run("b", [])).judgeChanged).toBe(true);
    expect(compareRuns(run("a", []), run("a", [])).judgeChanged).toBe(false);
  });

  it("keeps errors out of the verdict split", () => {
    const comparison = compareRuns(
      run("m", [result("a", true, "error")]),
      run("m", [result("a", true, "correct")]),
    );
    expect(comparison.base).toMatchObject({ errors: 1, correct: 0, total: 1 });
  });

  it("lists only the fields that changed", () => {
    const comparison = compareRuns(
      run("m", [result("a", true, "correct")]),
      run("m", [result("a", true, "partial")]),
    );
    expect(comparison.flips).toEqual([
      { pairId: "a", verdict: ["correct", "partial"] },
    ]);
  });
});

describe("compareRuns across languages", () => {
  it("pairs a translated run's results with the source's through headToBase", () => {
    const source = run("m", [
      result("en-1", true, "correct"),
      result("en-2", true, "correct"),
    ]);
    const translated = run("m", [
      result("id-1", false, "wrong"),
      result("id-2", true, "correct"),
    ]);
    const headToBase = new Map([
      ["id-1", "en-1"],
      ["id-2", "en-2"],
    ]);

    const comparison = compareRuns(source, translated, { headToBase });

    expect(comparison.commonPairIds).toEqual(["en-1", "en-2"]);
    expect(comparison.base.hits).toBe(2);
    expect(comparison.head.hits).toBe(1);
    expect(comparison.flips).toEqual([
      { pairId: "en-1", hit: [true, false], verdict: ["correct", "wrong"] },
    ]);
  });

  it("leaves out a translated pair with no source", () => {
    const comparison = compareRuns(
      run("m", [result("en-1", true, "correct")]),
      run("m", [result("id-9", true, "correct")]),
      { headToBase: new Map() },
    );
    expect(comparison.commonPairIds).toEqual([]);
  });
});

describe("stamp differences", () => {
  it("flags a chat model or prompt version change apart from the judge", () => {
    const base = {
      ...run("j", []),
      chatModel: "a",
      promptVersion: "1",
      judgePromptVersion: "1",
    };
    expect(compareRuns(base, { ...base, chatModel: "b" }).otherStampsChanged).toBe(
      true,
    );
    expect(compareRuns(base, { ...base, promptVersion: "2" }).otherStampsChanged).toBe(
      true,
    );
    expect(
      compareRuns(base, { ...base, judgePromptVersion: "2" }).otherStampsChanged,
    ).toBe(true);
    expect(compareRuns(base, { ...base }).otherStampsChanged).toBe(false);
  });
});

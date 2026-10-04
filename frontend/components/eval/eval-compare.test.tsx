import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvalCompare } from "@/components/eval/eval-compare";
import type { EvalPair, EvalResult, EvalRunDetail } from "@/lib/api/types";

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

function run(id: string, judgeModel: string, results: EvalResult[]): EvalRunDetail {
  return { id, judgeModel, results } as EvalRunDetail;
}

const PAIRS = [{ id: "b", question: "How is the token refreshed?" }] as EvalPair[];

describe("EvalCompare", () => {
  it("warns when the judge model differs", () => {
    render(
      <EvalCompare
        base={run("1", "judge-a", [result("b", true, "wrong")])}
        head={run("2", "judge-b", [result("b", true, "correct")])}
        pairs={PAIRS}
      />,
    );
    expect(
      screen.getByText(
        "These runs were judged by different models. Verdict changes may reflect the judge, not the answers. Retrieval hits are unaffected.",
      ),
    ).toBeInTheDocument();
  });

  it("says how many pairs it compared, and lists the flips", () => {
    render(
      <EvalCompare
        base={run("1", "m", [result("a", true, "correct"), result("b", true, "wrong")])}
        head={run("2", "m", [result("b", false, "correct")])}
        pairs={PAIRS}
      />,
    );
    expect(
      screen.getByText("Compared on 1 pairs both runs answered"),
    ).toBeInTheDocument();
    expect(screen.getByText("How is the token refreshed?")).toBeInTheDocument();
    expect(screen.queryByText(/judged by different models/)).not.toBeInTheDocument();
  });

  it("says nothing changed when there are no flips", () => {
    render(
      <EvalCompare
        base={run("1", "m", [result("b", true, "correct")])}
        head={run("2", "m", [result("b", true, "correct")])}
        pairs={PAIRS}
      />,
    );
    expect(screen.getByText("No pair changed between these runs.")).toBeInTheDocument();
  });
});

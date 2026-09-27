import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FeedbackSummary } from "@/components/output-feedback/feedback-summary";

describe("FeedbackSummary", () => {
  it("shows a down-vote rate per feature and per prompt version", () => {
    render(
      <FeedbackSummary
        summary={{
          byFeature: [{ feature: "answer", up: 3, down: 1 }],
          byReason: [{ feature: "answer", reasonCode: "wrong_file_cited", count: 1 }],
          byPromptVersion: [{ promptVersion: "abcdefabcdef", up: 3, down: 1 }],
        }}
      />,
    );

    // "Ask answers" renders twice with this data: once as the stat card's title,
    // once as the by-reason table's feature cell -- both from the same
    // `FEATURE_LABELS["answer"]` lookup, so `getAllByText` is correct here rather
    // than a workaround for a missing `data-testid`.
    expect(screen.getAllByText("Ask answers").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("25%")).toHaveLength(2);
    expect(screen.getByText("Cited the wrong file")).toBeInTheDocument();
    expect(screen.getByText("abcdefabcdef")).toBeInTheDocument();
  });
});

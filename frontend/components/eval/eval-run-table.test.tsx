import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EvalRunTable } from "@/components/eval/eval-run-table";
import type { EvalRunSummary } from "@/lib/api/types";

const RUN: EvalRunSummary = {
  id: "r1",
  setId: "s1",
  status: "done",
  error: null,
  promptVersion: null,
  judgePromptVersion: null,
  chatProvider: null,
  chatModel: "model-x",
  judgeModel: null,
  embeddingModel: null,
  projectGeneration: 1,
  pairsAnswered: 10,
  hits: 8,
  correct: 6,
  partial: 2,
  wrong: 2,
  errors: 0,
  startedAt: null,
  finishedAt: null,
  createdAt: "2026-10-01T10:00:00Z",
};

describe("EvalRunTable", () => {
  it("opens a run from a real button, and the row itself is not interactive", async () => {
    const onSelect = vi.fn();
    render(<EvalRunTable runs={[RUN]} onSelect={onSelect} />);

    const row = screen.getAllByRole("row")[1];
    expect(row).not.toHaveAttribute("tabindex");

    await userEvent.click(screen.getByRole("button", { name: /open run from/i }));
    expect(onSelect).toHaveBeenCalledWith("r1");
  });

  it("renders a pagination footer and reports the page asked for", async () => {
    const onPageChange = vi.fn();
    render(
      <EvalRunTable
        runs={[RUN]}
        onSelect={vi.fn()}
        pagination={{ page: 1, totalPages: 2, totalCount: 101, onPageChange }}
      />,
    );

    expect(screen.getByText("Page 1 of 2 · 101 total")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it("opens the run from the keyboard with Space", async () => {
    const onSelect = vi.fn();
    render(<EvalRunTable runs={[RUN]} onSelect={onSelect} />);

    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect(onSelect).toHaveBeenCalledWith("r1");
  });
});

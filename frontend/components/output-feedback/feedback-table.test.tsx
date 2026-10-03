import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FeedbackTable } from "@/components/output-feedback/feedback-table";
import type { FeedbackAdminRead } from "@/lib/api/types";

const row: FeedbackAdminRead = {
  id: "f1",
  projectId: "p1",
  projectName: "payments",
  targetType: "message",
  feature: "answer",
  rating: "down",
  reasonCodes: ["wrong_file_cited"],
  note: "Wrong file entirely.",
  promptVersion: "abcdefabcdef",
  createdOn: "2026-09-27",
  traceUrl: null,
};

describe("FeedbackTable", () => {
  it("shows the vote's day only, never a time", () => {
    // `createdOn` is a bare date (`.claude/rules/feedback.md` §2): rendering it with
    // a clock time, or as a relative "3 hours ago", would reintroduce the precision
    // the backend deliberately withholds.
    render(<FeedbackTable rows={[row]} isLoading={false} />);

    const cell = screen.getByText("2026-09-27");
    expect(cell).toBeInTheDocument();
    expect(screen.queryByText(/ago/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\d{2}:\d{2}/)).not.toBeInTheDocument();
  });
});

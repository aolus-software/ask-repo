import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FeedbackFilters } from "@/components/output-feedback/feedback-filters";

describe("FeedbackFilters", () => {
  it("names every control with a visible label", () => {
    render(<FeedbackFilters currentFilters={{}} onFiltersChange={() => {}} />);

    expect(screen.getByLabelText("Filter by feature")).toBeInTheDocument();
    expect(screen.getByLabelText("Filter by vote")).toBeInTheDocument();
    expect(screen.getByLabelText("Filter by reason")).toBeInTheDocument();
    expect(screen.getByLabelText("From date")).toHaveAttribute("type", "date");
    expect(screen.getByLabelText("To date")).toHaveAttribute("type", "date");
    // A visible label, not just an accessible name.
    expect(screen.getByText("From date").tagName).toBe("LABEL");
  });
});

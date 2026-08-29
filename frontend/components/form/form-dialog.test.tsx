import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FormError } from "@/components/form/form-error";
import { ApiError } from "@/lib/api/errors";

describe("FormError", () => {
  it("renders the banner when the backend named no fields", () => {
    render(<FormError error={new ApiError(409, "LAST_ADMIN", "That is the last admin.")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("That is the last admin.");
  });

  it("renders NOTHING when the backend named fields", () => {
    // Those messages render against their own inputs; a banner repeating them is
    // noise (forms.md §4).
    const error = new ApiError(422, "VALIDATION_ERROR", "Invalid request.", {
      repoUrl: "Must be https.",
    });
    const { container } = render(<FormError error={error} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when there is no error", () => {
    const { container } = render(<FormError error={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a generic message for a non-ApiError", () => {
    render(<FormError error={new Error("kaboom")} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});

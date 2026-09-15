import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LastOwnerNotice } from "@/components/users/last-owner-notice";
import { ApiError } from "@/lib/api/errors";

describe("LastOwnerNotice", () => {
  it("names every blocking project", () => {
    const error = new ApiError(409, "LAST_OWNER", "Would leave projects ownerless.", {}, {
      projects: [
        { id: "p1", name: "payments-api" },
        { id: "p2", name: "web" },
      ],
    });

    render(<LastOwnerNotice error={error} />);

    expect(screen.getByText("payments-api")).toBeInTheDocument();
    expect(screen.getByText("web")).toBeInTheDocument();
  });

  it("links each project to where the ownership is fixed", () => {
    const error = new ApiError(409, "LAST_OWNER", "Would leave projects ownerless.", {}, {
      projects: [{ id: "p1", name: "payments-api" }],
    });

    render(<LastOwnerNotice error={error} />);

    expect(screen.getByRole("link", { name: "payments-api" })).toHaveAttribute(
      "href",
      "/projects/p1",
    );
  });

  it("renders nothing for a different error code", () => {
    const error = new ApiError(409, "LAST_ADMIN", "That is the last admin.");

    const { container } = render(<LastOwnerNotice error={error} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a non-ApiError", () => {
    const { container } = render(<LastOwnerNotice error={new Error("kaboom")} />);

    expect(container).toBeEmptyDOMElement();
  });
});

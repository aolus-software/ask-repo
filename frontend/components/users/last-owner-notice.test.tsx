import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LastOwnerNotice } from "@/components/users/last-owner-notice";
import { ApiError } from "@/lib/api/errors";

describe("LastOwnerNotice", () => {
  it("names every blocking project", () => {
    const error = new ApiError(
      409,
      "LAST_OWNER",
      "Would leave projects ownerless.",
      {},
      {
        projects: [
          { id: "p1", name: "payments-api" },
          { id: "p2", name: "web" },
        ],
      },
    );

    render(<LastOwnerNotice error={error} />);

    expect(screen.getByText("payments-api")).toBeInTheDocument();
    expect(screen.getByText("web")).toBeInTheDocument();
  });

  it("links each project to where the ownership is fixed", () => {
    const error = new ApiError(
      409,
      "LAST_OWNER",
      "Would leave projects ownerless.",
      {},
      {
        projects: [{ id: "p1", name: "payments-api" }],
      },
    );

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

  const lastOwner = (names: string[]) =>
    new ApiError(
      409,
      "LAST_OWNER",
      "Would leave projects ownerless.",
      {},
      {
        projects: names.map((name, i) => ({ id: `p${i + 1}`, name })),
      },
    );

  it.each([
    [["alpha"], "alpha"],
    [["alpha", "beta"], "alpha and beta"],
    [["alpha", "beta", "gamma"], "alpha, beta, and gamma"],
  ])("renders %j as a joined list of links", (names, joined) => {
    const { container } = render(<LastOwnerNotice error={lastOwner(names)} />);

    expect(container.querySelector("p")?.textContent).toContain(`: ${joined}.`);
    names.forEach((name, i) => {
      expect(screen.getByRole("link", { name })).toHaveAttribute(
        "href",
        `/projects/p${i + 1}`,
      );
    });
  });

  it("links two projects with the same name to their own ids", () => {
    render(<LastOwnerNotice error={lastOwner(["api", "api"])} />);

    const links = screen.getAllByRole("link", { name: "api" });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/projects/p1",
      "/projects/p2",
    ]);
  });
});

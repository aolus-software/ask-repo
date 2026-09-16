import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuditChangeList } from "@/components/audit/audit-change-list";

describe("AuditChangeList", () => {
  it("renders a create as an added value, not as 'null'", () => {
    render(
      <AuditChangeList changed={{ email: { before: null, after: "new@example.com" } }} />,
    );

    expect(screen.getByText("new@example.com")).toBeInTheDocument();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
  });

  it("renders a delete as a removed value, not as 'null'", () => {
    render(<AuditChangeList changed={{ name: { before: "Billing", after: null } }} />);

    expect(screen.getByText("Billing")).toBeInTheDocument();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
  });

  it("renders both sides of an update", () => {
    render(<AuditChangeList changed={{ isAdmin: { before: false, after: true } }} />);

    expect(screen.getByText("false")).toBeInTheDocument();
    expect(screen.getByText("true")).toBeInTheDocument();
  });

  it("renders a list value without collapsing it to a string", () => {
    render(
      <AuditChangeList
        changed={{ permissions: { before: ["project.read"], after: ["project.read", "project.delete"] } }}
      />,
    );

    expect(screen.getByText("project.delete")).toBeInTheDocument();
  });
});

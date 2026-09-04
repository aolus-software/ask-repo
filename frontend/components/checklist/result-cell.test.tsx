import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ResultCell } from "@/components/checklist/result-cell";

const item = {
  id: "i1",
  moduleId: "m",
  projectId: "p",
  feature: "Login",
  testName: "Rejects a wrong password",
  expectedResult: "401",
  currentResult: null,
  status: "untested" as const,
  notes: null,
  citations: null,
  source: "generated" as const,
  kind: "positive" as const,
  position: 0,
  createdBy: "someone-else",
  reviewedBy: null,
  reviewedAt: null,
  createdAt: "2026-09-01T00:00:00Z",
  updatedAt: "2026-09-01T00:00:00Z",
};

describe("ResultCell", () => {
  it("is editable by a user who did not author the checklist", () => {
    /**
     * The ungated write (spec 2.5). A tester must be able to record what they saw
     * without being able to rewrite what was expected — so this control is enabled for
     * everyone, and the definition columns are the ones that are gated.
     */
    render(<ResultCell item={item} onSave={vi.fn()} canEditDefinition={false} />);

    expect(screen.getByRole("textbox", { name: /current result/i })).toBeEnabled();
    expect(screen.getByRole("combobox", { name: /status/i })).toBeEnabled();
  });

  it("shows no prefilled observation for an untested row", () => {
    /** AskRepo has not run the application and will not claim to have (spec 2.3). */
    render(<ResultCell item={item} onSave={vi.fn()} canEditDefinition={false} />);

    expect(screen.getByRole("textbox", { name: /current result/i })).toHaveValue("");
  });
});

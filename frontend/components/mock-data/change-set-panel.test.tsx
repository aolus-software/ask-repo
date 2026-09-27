import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MockDataChangeSetPanel } from "@/components/mock-data/change-set-panel";
import type {
  MockDataChangeSetResponse,
  MockDataRecordResponse,
} from "@/lib/api/types";

const RECORDS: MockDataRecordResponse[] = [
  {
    id: "r1",
    checklistModuleId: "m1",
    fields: { name: "Ada" },
    createdBy: "u1",
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
  },
];

const CHANGE_SET: MockDataChangeSetResponse = {
  id: "cs1",
  checklistModuleId: "m1",
  origin: "chat",
  messageId: "msg1",
  summary: "A mixed set of proposed record changes",
  operations: [
    { op: "add", id: "op-add", rationale: "New record", fields: { name: "Grace" } },
    {
      op: "update",
      id: "op-update",
      rationale: "Fix a typo",
      recordId: "r1",
      changes: { name: "Ada Lovelace" },
    },
    { op: "remove", id: "op-remove", rationale: "Duplicate", recordId: "r1" },
  ],
  status: "pending",
  resolvedBy: null,
  resolvedAt: null,
  createdBy: "u1",
  createdAt: "2026-01-01T00:00:00Z",
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MockDataChangeSetPanel
        changeSet={CHANGE_SET}
        moduleId="m1"
        records={RECORDS}
        canApply
      />
    </QueryClientProvider>,
  );
}

describe("MockDataChangeSetPanel", () => {
  it("groups a mixed change set into Added/Changed/Removed sections, with a count line", () => {
    renderPanel();

    expect(screen.getByText("1 added, 1 changed, 1 removed")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Added" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Changed" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Removed" })).toBeInTheDocument();
  });

  it("omits a section for an operation kind that is not present", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MockDataChangeSetPanel
          changeSet={{
            ...CHANGE_SET,
            operations: [CHANGE_SET.operations[0]],
          }}
          moduleId="m1"
          records={RECORDS}
          canApply
        />
      </QueryClientProvider>,
    );

    expect(screen.getByText("1 added, 0 changed, 0 removed")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Added" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Changed" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Removed" })).toBeNull();
  });
});

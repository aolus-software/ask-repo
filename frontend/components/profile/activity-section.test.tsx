import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActivitySection } from "@/components/profile/activity-section";
import type { ActivityEntry, MembershipSummary, PaginatedResponse } from "@/lib/api/types";

function page(items: ActivityEntry[]): PaginatedResponse<ActivityEntry> {
  return { items, page: 1, limit: 20, totalCount: items.length, totalPages: 1 };
}

function entry(overrides: Partial<ActivityEntry>): ActivityEntry {
  return {
    id: "e1",
    createdAt: new Date().toISOString(),
    eventType: "conversation.created",
    outcome: "success",
    targetLabel: null,
    projectId: null,
    ipAddress: "203.0.113.9",
    ...overrides,
  };
}

const memberships: MembershipSummary[] = [
  { projectId: "p1", projectName: "Acme API", role: "editor" },
];

function renderSection(items: ActivityEntry[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("/me/memberships")) return Response.json(memberships);
      if (url.includes("/me/activity")) return Response.json(page(items));
      throw new Error(`unexpected fetch: ${url}`);
    }),
  );
  return render(
    <QueryClientProvider client={client}>
      <ActivitySection />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("ActivitySection", () => {
  it("shows the targetLabel when the row has one", async () => {
    renderSection([
      entry({ id: "e1", eventType: "project.created", targetLabel: "Acme API" }),
    ]);
    expect(await screen.findByText("Acme API")).toBeInTheDocument();
  });

  it("links a targetLabel-less row to the project, named from memberships", async () => {
    renderSection([
      entry({ id: "e2", eventType: "conversation.created", targetLabel: null, projectId: "p1" }),
    ]);
    const link = await screen.findByRole("link", { name: "Acme API" });
    expect(link).toHaveAttribute("href", "/projects/p1");
  });

  it("falls back to a dash when there is no label and no project", async () => {
    renderSection([
      entry({ id: "e3", eventType: "auth.login.succeeded", targetLabel: null, projectId: null }),
    ]);
    expect(await screen.findAllByText("—")).not.toHaveLength(0);
  });
});

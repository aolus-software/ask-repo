import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EvalSetTable } from "@/components/eval/eval-set-table";
import type { EvalRunSummary, EvalSetSummary } from "@/lib/api/types";

const RUN: EvalRunSummary = {
  id: "r1",
  setId: "s1",
  status: "done",
  error: null,
  promptVersion: "v1",
  chatProvider: "ollama",
  chatModel: "m",
  judgeModel: "m",
  embeddingModel: "e",
  projectGeneration: 1,
  pairsAnswered: 25,
  hits: 22,
  correct: 17,
  partial: 5,
  wrong: 3,
  errors: 0,
  startedAt: null,
  finishedAt: null,
  createdAt: "2026-10-01T10:00:00Z",
};

function makeSet(overrides: Partial<EvalSetSummary> = {}): EvalSetSummary {
  return {
    id: "s1",
    projectId: "p1",
    name: "Auth questions",
    sourcePath: "backend/app/auth",
    requestedCount: 25,
    mix: "balanced",
    status: "ready",
    error: null,
    pairCount: 25,
    indexedGeneration: 1,
    createdAt: "2026-10-01T09:00:00Z",
    latestRun: RUN,
    ...overrides,
  };
}

function page(items: EvalSetSummary[]) {
  return { items, page: 1, limit: 100, totalCount: items.length, totalPages: 1 };
}

function renderTable() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EvalSetTable projectId="p1" />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("EvalSetTable", () => {
  it("renders a set's name, path, pair count, status and latest run tally", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(page([makeSet()]))),
    );
    renderTable();

    expect(await screen.findByText("Auth questions")).toBeInTheDocument();
    expect(screen.getByText("backend/app/auth")).toBeInTheDocument();
    expect(screen.getByText("25")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(
      screen.getByText("hits 22/25 · correct 17 · partial 5 · wrong 3"),
    ).toBeInTheDocument();
  });

  it("says Whole project for a set with no path, and no run yet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(page([makeSet({ sourcePath: null, latestRun: null })])),
      ),
    );
    renderTable();

    expect(await screen.findByText("Whole project")).toBeInTheDocument();
    expect(screen.getByText("No runs yet")).toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(page([]))),
    );
    renderTable();

    expect(await screen.findByText("No eval sets yet")).toBeInTheDocument();
  });

  it("links each row to its set", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(page([makeSet()]))),
    );
    renderTable();

    const link = await screen.findByRole("link", { name: "Auth questions" });
    expect(link).toHaveAttribute("href", "/projects/p1/eval/s1");
  });
});

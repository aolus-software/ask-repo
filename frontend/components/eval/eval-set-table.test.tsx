import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EvalSetTable } from "@/components/eval/eval-set-table";
import type { EvalRunSummary, EvalSetSummary } from "@/lib/api/types";

const RUN: EvalRunSummary = {
  id: "r1",
  setId: "s1",
  status: "done",
  error: null,
  promptVersion: "v1",
  judgePromptVersion: "j1",
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
    language: "en",
    sourceSetId: null,
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

  it("shows each set's language in its own name", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          page([makeSet(), makeSet({ id: "s2", name: "Auth ja", language: "ja" })]),
        ),
      ),
    );
    renderTable();

    expect(await screen.findByText("English")).toBeInTheDocument();
    expect(screen.getByText("日本語")).toBeInTheDocument();
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

describe("EvalSetTable pagination", () => {
  it("pages with page and limit only, and shows the footer past one page", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const next = String(url).includes("page=2");
      return Response.json({
        items: [
          makeSet({
            id: next ? "s2" : "s1",
            name: next ? "Second page" : "First page",
          }),
        ],
        page: next ? 2 : 1,
        limit: 100,
        totalCount: 101,
        totalPages: 2,
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderTable();

    expect(await screen.findByText("First page")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 2 · 101 total")).toBeInTheDocument();
    const first = new URL(String(fetchMock.mock.calls[0][0]), "http://x");
    expect([...first.searchParams.keys()].sort()).toEqual(["limit", "page"]);

    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Second page")).toBeInTheDocument();
    expect(screen.getByText("Page 2 of 2 · 101 total")).toBeInTheDocument();
  });

  it("shows no footer for a single page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(page([makeSet()]))),
    );
    renderTable();

    await screen.findByText("Auth questions");
    expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
  });

  it("offers Generate in the empty state for a caller who may run evals", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(page([]))),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <EvalSetTable projectId="p1" permissions={["eval.run"]} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("No eval sets yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate/i })).toBeInTheDocument();
  });
});

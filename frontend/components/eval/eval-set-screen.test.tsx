import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EvalSetScreen } from "@/components/eval/eval-set-screen";
import { PERMISSION } from "@/lib/can";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const RUN_BASE = {
  id: "r1",
  setId: "s1",
  status: "done",
  createdAt: "2026-10-01T10:00:00Z",
};
const RUN_HEAD = { ...RUN_BASE, id: "r2", createdAt: "2026-10-01T10:00:00Z" };

function stubApi(permissions: string[]) {
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
    const path = String(url);
    if (_init?.method === "DELETE") return new Response(null, { status: 204 });
    if (path.endsWith("/eval-sets/s1"))
      return Response.json({
        id: "s1",
        projectId: "p1",
        name: "Smoke",
        sourcePath: null,
        status: "ready",
        pairCount: 1,
        pairs: [],
        indexedGeneration: null,
        projectGeneration: 1,
        error: null,
      });
    if (path.includes("/eval-sets/s1/runs"))
      return Response.json({ items: [RUN_BASE, RUN_HEAD], total: 2 });
    if (path.includes("/eval-runs/"))
      return Response.json({
        ...RUN_BASE,
        id: path.split("/").pop(),
        judgeModel: "j",
        results: [],
      });
    if (path.endsWith("/projects/p1"))
      return Response.json({ id: "p1", name: "Proj", permissions });
    return Response.json({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EvalSetScreen projectId="p1" setId="s1" />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("EvalSetScreen", () => {
  it("shows not-found and fetches no eval data without eval.read", async () => {
    const fetchMock = stubApi([]);
    renderScreen();

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u]) => String(u).endsWith("/projects/p1")),
      ).toBe(true),
    );
    await screen.findByText(/not found|does not exist/i);
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/eval-"))).toBe(
      false,
    );
  });

  it("compares two different runs and will not pair a run with itself", async () => {
    stubApi([PERMISSION.EVAL_READ]);
    renderScreen();

    await userEvent.click(await screen.findByRole("combobox", { name: "Base run" }));
    const first = await screen.findAllByRole("option");
    await userEvent.click(first[0]);

    await userEvent.click(screen.getByRole("combobox", { name: "Head run" }));
    const second = await screen.findAllByRole("option");
    expect(second[0]).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(second[1]);

    await screen.findByText(/No pair changed between these runs/);
  });

  it("shows an error, not not-found, when the project fails to load", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          { detail: { code: "INTERNAL", message: "boom" } },
          { status: 500 },
        ),
      ),
    );
    renderScreen();

    expect(await screen.findByText("Could not load this page")).toBeInTheDocument();
  });

  it("offers delete only with eval.run, and goes back to the Eval tab after", async () => {
    const fetchMock = stubApi([PERMISSION.EVAL_READ, PERMISSION.EVAL_RUN]);
    renderScreen();

    await userEvent.click(await screen.findByRole("button", { name: "Delete Smoke" }));
    expect(
      await screen.findByText(/every run and all of their results/),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete eval set" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects/p1#eval"));
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(
      true,
    );
  });

  it("hides delete without eval.run", async () => {
    stubApi([PERMISSION.EVAL_READ]);
    renderScreen();

    await screen.findByText("Smoke");
    expect(screen.queryByRole("button", { name: "Delete Smoke" })).toBeNull();
  });
});

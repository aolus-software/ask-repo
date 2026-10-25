import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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
        language: "en",
        sourceSetId: null,
        pairCount: 1,
        pairs: [],
        indexedGeneration: null,
        projectGeneration: 1,
        error: null,
      });
    if (path.includes("/eval-sets/s1/runs"))
      return Response.json({ items: [RUN_BASE, RUN_HEAD], total: 2 });
    if (path.includes("/projects/p1/eval-sets"))
      return Response.json({ items: [], total: 0 });
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

const runDetail = (id: string, pairId: string, hit: boolean) => ({
  id,
  setId: "x",
  status: "done",
  createdAt: "2026-10-01T10:00:00Z",
  chatModel: "m",
  judgeModel: "j",
  promptVersion: "p",
  judgePromptVersion: "q",
  results: [
    {
      id: `r-${id}`,
      pairId,
      retrievalHit: hit,
      verdict: "correct",
      judgeReason: null,
      answer: "",
      groundingWarnings: [],
      retrievalAttempts: 1,
    },
  ],
});

function stubTranslated(
  permissions: string[],
  source: "found" | "gone",
  runs: boolean = false,
  reincluded: boolean = false,
) {
  const pair = (
    id: string,
    sourcePairId: string,
    question: string,
    excluded: boolean = true,
  ) => ({
    id,
    position: 0,
    questionType: "explain",
    question,
    referenceAnswer: "x",
    sourceFile: "a.py",
    startLine: 1,
    endLine: 2,
    excluded,
    sourcePairId,
    exclusionReason: "translation_unfaithful",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const path = String(url);
      if (runs) {
        const summary = (id: string, setId: string) => ({
          items: [{ id, setId, status: "done", createdAt: "2026-10-01T10:00:00Z" }],
          total: 1,
        });
        if (path.includes("/eval-sets/src/runs"))
          return Response.json(summary("src-run", "src"));
        if (path.includes("/eval-sets/s1/runs"))
          return Response.json(summary("t-run", "s1"));
        if (path.endsWith("/eval-runs/src-run"))
          return Response.json(runDetail("src-run", "ea", true));
        if (path.endsWith("/eval-runs/t-run"))
          return Response.json(runDetail("t-run", "a", false));
      }
      if (path.endsWith("/eval-sets/s1"))
        return Response.json({
          id: "s1",
          projectId: "p1",
          name: "Auth · id",
          sourcePath: null,
          status: "ready",
          language: "id",
          sourceSetId: "src",
          pairCount: 2,
          pairs: [pair("a", "ea", "Apa?"), pair("b", "eb", "Bagaimana?", !reincluded)],
          indexedGeneration: 1,
          projectGeneration: 1,
          error: null,
        });
      if (path.endsWith("/eval-sets/src"))
        return source === "found"
          ? Response.json({
              id: "src",
              name: "Auth",
              language: "en",
              sourceSetId: null,
              pairs: [],
            })
          : Response.json(
              {
                detail: { code: "EVAL_SET_NOT_FOUND", message: "Eval set not found." },
              },
              { status: 404 },
            );
      if (path.includes("/runs")) return Response.json({ items: [], total: 0 });
      if (path.endsWith("/projects/p1"))
        return Response.json({ id: "p1", name: "Proj", permissions });
      if (path.includes("/projects/p1/eval-sets"))
        return Response.json({ items: [], total: 0 });
      return Response.json({});
    }),
  );
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
  it("shows forbidden, not not-found, and fetches no eval data without eval.read", async () => {
    const fetchMock = stubApi([]);
    renderScreen();

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u]) => String(u).endsWith("/projects/p1")),
      ).toBe(true),
    );
    await screen.findByText("You do not have access to this");
    expect(screen.queryByText(/not found|does not exist/i)).toBeNull();
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

  it("offers Translate on a ready English set to an eval.run holder", async () => {
    stubApi([PERMISSION.EVAL_READ, PERMISSION.EVAL_RUN]);
    renderScreen();
    expect(
      await screen.findByRole("button", { name: /^translate$/i }),
    ).toBeInTheDocument();
  });

  it("does not offer Translate to a viewer", async () => {
    stubApi([PERMISSION.EVAL_READ]);
    renderScreen();
    await screen.findByText("Smoke");
    expect(screen.queryByRole("button", { name: /^translate$/i })).toBeNull();
  });

  it("names its source and counts the unfaithful questions on a translated set", async () => {
    stubTranslated([PERMISSION.EVAL_READ, PERMISSION.EVAL_RUN], "found");
    renderScreen();
    expect(await screen.findByText("Translated from Auth")).toBeInTheDocument();
    expect(
      screen.getByText(
        "2 questions could not be translated with their code kept intact, and are excluded from runs.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^translate$/i })).toBeNull();
  });

  it("counts only still-excluded unfaithful pairs in the banner", async () => {
    stubTranslated([PERMISSION.EVAL_READ], "found", false, true);
    renderScreen();
    expect(
      await screen.findByText(
        "1 question could not be translated with their code kept intact, and are excluded from runs.",
      ),
    ).toBeInTheDocument();
  });

  it("says when its source has been deleted", async () => {
    stubTranslated([PERMISSION.EVAL_READ], "gone");
    renderScreen();
    expect(
      await screen.findByText("Translated from a set that has since been deleted"),
    ).toBeInTheDocument();
  });

  it("compares a translated run with a source run, labelled by language", async () => {
    stubTranslated([PERMISSION.EVAL_READ], "found", true);
    renderScreen();

    await userEvent.click(await screen.findByRole("combobox", { name: "Source run" }));
    await userEvent.click((await screen.findAllByRole("option"))[0]);
    await userEvent.click(screen.getByRole("combobox", { name: "Translated run" }));
    await userEvent.click((await screen.findAllByRole("option"))[0]);

    expect(await screen.findByText("English:")).toBeInTheDocument();
    expect(screen.getByText("Bahasa Indonesia:")).toBeInTheDocument();
    // The source run hit and the translated one missed, on the pair they share.
    // (The pair table lists the question too, so look inside the comparison.)
    const comparison = screen
      .getByText("English:")
      .closest("div.space-y-3") as HTMLElement;
    expect(within(comparison).getByText("Apa?")).toBeInTheDocument();
  });

  it("offers no source comparison once the source is deleted", async () => {
    stubTranslated([PERMISSION.EVAL_READ], "gone", true);
    renderScreen();

    await screen.findByText("Translated from a set that has since been deleted");
    expect(screen.queryByText("Compare with source")).toBeNull();
  });
});
